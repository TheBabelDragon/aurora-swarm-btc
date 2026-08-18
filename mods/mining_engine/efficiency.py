"""
Efficiency loop — hashrate/power when hardware stats exist (ASIC RPC / future).
Pool-only mode continues without local silicon.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("aurora.mining.efficiency")


class EfficiencyLoop:
    def __init__(
        self,
        get_stats: Callable[[], Optional[dict]],
        *,
        on_sample: Optional[Callable[[dict], None]] = None,
        interval: float = 30.0,
    ):
        self.get_stats = get_stats
        self.on_sample = on_sample
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last: Optional[dict] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="eff-loop", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                stats = self.get_stats() or {}
                hashrate = float(stats.get("hashrate") or stats.get("hashrate_hs") or 0)
                power = float(stats.get("power") or 0)
                efficiency = (hashrate / power) if power > 0 else None
                sample = {
                    "hashrate": hashrate,
                    "power": power,
                    "efficiency": efficiency,
                    "ts": time.time(),
                    "mode": "hardware" if hashrate or power else "pool_only",
                }
                self.last = sample
                if self.on_sample:
                    self.on_sample(sample)
                if sample["mode"] == "pool_only":
                    logger.debug("No local ASIC/GPU stats — pool-only mode")
            except Exception as e:
                logger.debug(f"efficiency: {e}")
            self._stop.wait(self.interval)
