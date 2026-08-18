"""MiningEngine — idempotent start, backoff restart, direct hashrate samples."""

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
        self._start_lock = threading.Lock()
        self._restart_backoff = 2.0
        self._last_restart_attempt = 0.0

    def _publish_hs(self, hs: float):
        if hs < 0:
            hs = 0.0
        running = False
        try:
            running = bool(self.backend.running()) and not self.paused
        except Exception:
            pass
        self.pipeline.last_hashrate_hs = hs
        self.pipeline.last_hashrate_ghs = hs / 1e9
        self.pipeline.last_hashrate_display = format_hashrate(hs, running=running)
        self._on_hashrate(hs / 1e9)
        try:
            payload = {
                "hashrate_hs": hs,
                "hashrate_ghs": hs / 1e9,
                "hashrate_display": format_hashrate(hs, running=running),
                "running": running,
                "status": "mining" if running else "stopped",
                "backend": getattr(self.backend, "kind", ""),
                "error": getattr(self.backend, "last_error", "") or "",
            }
            self.comms.set_state(f"worker:{self.worker_id}:hashrate", payload, expire=120)
            self.comms.set_state("cluster:total_hashrate_hs", hs)
        except Exception:
            pass

    def _on_hashrate(self, gh: float):
        pass

    def start(self) -> bool:
        """Idempotent — never stack duplicate worker threads."""
        with self._start_lock:
            self.paused = False
            self._stop.clear()
            try:
                if self.backend.running():
                    ok = True
                else:
                    ok = bool(self.backend.start())
            except Exception as e:
                logger.warning(f"backend start: {e}")
                ok = False
            if ok and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._loop, name="mining-engine", daemon=True)
                self._thread.start()
            self._restart_backoff = 2.0
            return ok

    def stop(self):
        self.paused = True
        self._stop.set()
        try:
            self.backend.stop()
        except Exception as e:
            logger.debug(f"backend stop: {e}")
        self._publish_hs(0.0)

    def restart(self):
        self.stop()
        time.sleep(1)
        self._stop.clear()
        return self.start()

    def set_intensity(self, intensity: str):
        self.cfg.intensity = str(intensity)
        try:
            self.backend.set_intensity(str(intensity))
        except Exception:
            pass

    def status(self) -> dict:
        hs = 0.0
        if hasattr(self.backend, "get_hashrate_hs"):
            try:
                hs = float(self.backend.get_hashrate_hs() or 0)
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
        try:
            running = bool(self.backend.running()) and not self.paused
        except Exception:
            running = False
        return {
            "worker_id": self.worker_id,
            "running": running,
            "paused": self.paused,
            "intensity": self.cfg.intensity,
            "pool": self.cfg.pool_url,
            "wallet": self.cfg.wallet,
            "coin": self.cfg.coin,
            "backend": getattr(self.backend, "kind", "unknown"),
            "backend_available": True,
            "hashrate_hs": hs,
            "hashrate_ghs": hs / 1e9,
            "hashrate_display": format_hashrate(hs, running=running),
            "error": err,
            **{
                k: v
                for k, v in self.pipeline.snapshot().items()
                if k not in ("hashrate_hs", "hashrate_ghs", "hashrate_display")
            },
            "fleet": self.coord.fleet_view() if hasattr(self.coord, "fleet_view") else {},
        }

    def _loop(self):
        while not self._stop.is_set():
            if self.paused:
                time.sleep(0.5)
                continue
            try:
                if not self.backend.running():
                    now = time.time()
                    if now - self._last_restart_attempt >= self._restart_backoff:
                        self._last_restart_attempt = now
                        logger.info(
                            "backend not running — restart (backoff=%.1fs)", self._restart_backoff
                        )
                        try:
                            self.backend.start()
                        except Exception as e:
                            logger.warning(f"restart failed: {e}")
                        self._restart_backoff = min(60.0, self._restart_backoff * 1.5)
                    time.sleep(1.0)
                    continue
                # healthy path resets backoff slowly
                self._restart_backoff = max(2.0, self._restart_backoff * 0.9)

                stream = self.backend.stdout() if hasattr(self.backend, "stdout") else None
                if stream:
                    try:
                        line = stream.readline()
                        if line:
                            self.pipeline.handle_line(line if isinstance(line, str) else line.decode(errors="ignore"))
                    except Exception:
                        pass

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
            except Exception as e:
                logger.debug(f"engine loop: {e}")
            time.sleep(0.05)
