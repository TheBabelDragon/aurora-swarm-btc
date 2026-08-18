"""MiningEngine — samples hashrate directly from backend every loop."""

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
from .share_pipeline import SharePipeline, format_hashrate

logger = logging.getLogger("aurora.mining.engine")


class MiningEngine:
    def __init__(self, comms: Any, **kwargs):
        self.comms = comms
        self.worker_id = kwargs.get("worker_id") or comms.node_id
        coin = (kwargs.get("coin") or os.getenv("AURORA_MINE_COIN", "BTC")).upper()
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
            coin=coin,
            comms=comms,
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
        self._last_sample = 0.0

    def _publish_hs(self, hs: float):
        if hs < 0:
            hs = 0.0
        self.pipeline.last_hashrate_hs = hs
        self.pipeline.last_hashrate_ghs = hs / 1e9
        self.pipeline.last_hashrate_display = format_hashrate(hs)
        self._on_hashrate(hs / 1e9)
        try:
            payload = {
                "hashrate_hs": hs,
                "hashrate_ghs": hs / 1e9,
                "hashrate_display": format_hashrate(hs),
                "ts": time.time(),
                "status": "mining" if self.backend.running() else "stopped",
            }
            self.comms.set_state(f"worker:{self.worker_id}:hashrate", payload, expire=120)
            self.comms.set_state("cluster:total_hashrate_hs", hs)
            self.comms.set_state("cluster:total_hashrate_ghs", hs / 1e9)
            self.comms.set_state("cluster:total_hashrate_btc", hs / 1e12)
        except Exception:
            pass

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
                "coin": self.cfg.coin,
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
        self._publish_hs(0.0)

    def restart(self):
        self.stop()
        time.sleep(1)
        self._stop.clear()
        return self.start()

    def set_intensity(self, intensity: str):
        self.cfg.intensity = str(intensity)
        self.backend.set_intensity(str(intensity))

    def status(self) -> dict:
        hs = 0.0
        if hasattr(self.backend, "get_hashrate_hs"):
            try:
                hs = float(self.backend.get_hashrate_hs())
            except Exception:
                hs = self.pipeline.last_hashrate_hs
        else:
            hs = self.pipeline.last_hashrate_hs
        err = ""
        if hasattr(self.backend, "last_error"):
            try:
                err = self.backend.last_error() or ""
            except Exception:
                pass
        return {
            "worker_id": self.worker_id,
            "running": self.backend.running(),
            "paused": self.paused,
            "intensity": self.cfg.intensity,
            "pool": self.cfg.pool_url,
            "wallet": self.cfg.wallet,
            "coin": self.cfg.coin,
            "backend": getattr(self.backend, "kind", "unknown"),
            "backend_available": self.backend.available(),
            "hashrate_hs": hs,
            "hashrate_ghs": hs / 1e9,
            "hashrate_display": format_hashrate(hs),
            "error": err,
            **{k: v for k, v in self.pipeline.snapshot().items() if k not in ("hashrate_hs", "hashrate_ghs", "hashrate_display")},
            "fleet": self.coord.fleet_view(),
        }

    def _loop(self):
        while not self._stop.is_set():
            if self.paused:
                time.sleep(0.5)
                continue
            if not self.backend.running():
                self.backend.start()
                time.sleep(2)
                continue

            # Drain stdout for share/job log lines
            stream = self.backend.stdout()
            if stream:
                try:
                    line = stream.readline()
                    if line:
                        self.pipeline.handle_line(line)
                except Exception:
                    pass

            # Direct hashrate sample — source of truth
            now = time.time()
            if now - self._last_sample >= 1.5:
                self._last_sample = now
                hs = 0.0
                if hasattr(self.backend, "get_hashrate_hs"):
                    try:
                        hs = float(self.backend.get_hashrate_hs() or 0)
                    except Exception:
                        hs = 0.0
                if hs <= 0 and self.pipeline.last_hashrate_hs > 0:
                    hs = self.pipeline.last_hashrate_hs
                self._publish_hs(hs)
                try:
                    self.comms.heartbeat(
                        metadata={
                            "status": "mining",
                            "hashrate_hs": hs,
                            "hashrate_display": format_hashrate(hs),
                            "backend": getattr(self.backend, "kind", ""),
                        }
                    )
                except Exception:
                    pass

            time.sleep(0.05)
