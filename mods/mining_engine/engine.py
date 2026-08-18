"""
MiningEngine — tandem brain around a hasher.
Backend: bfgminer if present, else pure-Python stratum CPU (always available).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

from .adaptive import AdaptiveIntensity
from .backends import MinerConfig, select_backend
from .coordinator import MiningCoordinator
from .defaults import DEFAULT_INTENSITY, DEFAULT_MINING_WALLET, DEFAULT_POOL_URL
from .share_pipeline import SharePipeline

logger = logging.getLogger("aurora.mining.engine")


class MiningEngine:
    def __init__(self, comms: Any, **kwargs):
        self.comms = comms
        self.worker_id = kwargs.get("worker_id") or comms.node_id
        self.cfg = MinerConfig(
            pool_url=kwargs.get("pool_url") or os.getenv("POOL_URL", DEFAULT_POOL_URL),
            wallet=kwargs.get("wallet")
            or os.getenv("MINING_WALLET", DEFAULT_MINING_WALLET)
            or DEFAULT_MINING_WALLET,
            worker_name=kwargs.get("worker_name") or self.worker_id,
            intensity=str(kwargs.get("intensity") or os.getenv("INTENSITY", DEFAULT_INTENSITY)),
            gpus=int(kwargs.get("gpus") or os.getenv("GPUS_PER_POD", "1")),
            binary=kwargs.get("binary") or os.getenv("BFGMINER_BIN", "bfgminer"),
            cpu_threads=int(kwargs.get("cpu_threads") or os.getenv("AURORA_CPU_THREADS", "0") or 0),
        )
        self.backend = select_backend(self.cfg)
        self.pipeline = SharePipeline(
            comms,
            worker_id=self.worker_id,
            pool_id=self.cfg.pool_url,
            facility_domain=kwargs.get("facility_domain") or os.getenv("FACILITY_DOMAIN", "unknown"),
            on_hashrate=self._on_hashrate,
        )
        self.adaptive = AdaptiveIntensity()
        self.coord = MiningCoordinator(comms)
        self.paused = False
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        # Adaptive intensity only meaningful for bfgminer GPU path
        self._adaptive_enabled = (
            getattr(self.backend, "kind", "") == "bfgminer"
            and os.getenv("AURORA_MINING_ADAPTIVE", "1") not in ("0", "false", "no")
        )
        self._last_adapt = 0.0

    def _on_hashrate(self, gh: float):
        self.adaptive.observe(gh)
        self.coord.publish_worker(
            self.worker_id,
            {
                **self.pipeline.snapshot(),
                "intensity": self.cfg.intensity,
                "paused": self.paused,
                "running": self.backend.running(),
                "pool": self.cfg.pool_url,
                "wallet": self.cfg.wallet,
                "backend": getattr(self.backend, "kind", "unknown"),
            },
        )

    def start(self) -> bool:
        self.paused = False
        ok = self.backend.start()
        if ok and (self._thread is None or not self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="mining-engine", daemon=True)
            self._thread.start()
        return ok

    def stop(self):
        self.paused = True
        self._stop.set()
        self.backend.stop()

    def restart(self):
        self.stop()
        time.sleep(1)
        self._stop.clear()
        return self.start()

    def set_intensity(self, intensity: str):
        self.cfg.intensity = str(intensity)
        self.backend.set_intensity(str(intensity))
        if self.backend.running() and getattr(self.backend, "kind", "") == "bfgminer":
            self.restart()

    def status(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "running": self.backend.running(),
            "paused": self.paused,
            "intensity": self.cfg.intensity,
            "pool": self.cfg.pool_url,
            "wallet": self.cfg.wallet,
            "wallet_set": bool(self.cfg.wallet),
            "backend": getattr(self.backend, "kind", "unknown"),
            "backend_available": self.backend.available(),
            "adaptive": self._adaptive_enabled,
            **self.pipeline.snapshot(),
            "fleet": self.coord.fleet_view(),
        }

    def _loop(self):
        while not self._stop.is_set():
            if self.paused:
                time.sleep(1)
                continue
            if not self.backend.running():
                self.backend.start()
                time.sleep(3)
                continue
            stream = self.backend.stdout()
            if not stream:
                time.sleep(1)
                continue
            try:
                line = stream.readline()
                if not line:
                    time.sleep(0.05)
                    continue
                self.pipeline.handle_line(line)
            except Exception as e:
                logger.debug(f"read line: {e}")
                time.sleep(1)

            now = time.time()
            if self._adaptive_enabled and now - self._last_adapt > 90:
                self._last_adapt = now
                try:
                    thermal = self.adaptive.thermal_hint_from_comms(self.comms)
                    nxt = self.adaptive.suggest(int(float(self.cfg.intensity)), thermal_scale=thermal)
                    if str(nxt) != str(self.cfg.intensity):
                        logger.info(f"adaptive intensity {self.cfg.intensity} → {nxt}")
                        self.set_intensity(str(nxt))
                except Exception as e:
                    logger.debug(f"adaptive: {e}")

            try:
                self.comms.heartbeat(
                    metadata={
                        "status": "mining" if self.backend.running() else "stopped",
                        "intensity": self.cfg.intensity,
                        "hashrate_ghs": self.pipeline.last_hashrate_ghs,
                        "backend": getattr(self.backend, "kind", "unknown"),
                    }
                )
            except Exception:
                pass
