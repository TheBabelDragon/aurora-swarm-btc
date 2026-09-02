"""
Background epoch commit tick.

An epoch tick is deterministic from the Bitcoin chain / anchor state.
It is never derived from time.time(), peer arrival, or torrent completion.
The interval only controls how often we *observe* the chain; the epoch
coordinate itself is the chain tip.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

from comms.layer import CommsLayer

from .epoch import EpochBuilder

logger = logging.getLogger("aurora.assets.epoch_tick")

DEFAULT_INTERVAL = float(os.getenv("AURORA_EPOCH_INTERVAL", "3600"))


class EpochTicker:
    def __init__(
        self,
        comms: CommsLayer,
        *,
        interval: float = DEFAULT_INTERVAL,
        possession: Any = None,
        topology_registry: Any = None,
        policy: Any = None,
        request_broadcast: bool = False,
        chain: Any = None,
    ):
        self.comms = comms
        self.interval = max(60.0, float(interval))
        self.possession = possession
        self.topology_registry = topology_registry
        self.policy = policy
        self.request_broadcast = request_broadcast
        self.chain = chain
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_result: Optional[dict] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="epoch-tick", daemon=True)
        self._thread.start()
        logger.info(f"EpochTicker started interval={self.interval}s")

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def tick_once(self) -> dict:
        b = EpochBuilder(self.comms, chain=self.chain)
        epoch = b.from_local_state(
            possession=self.possession,
            topology_registry=self.topology_registry,
            policy=self.policy,
            note="epoch_tick",
        )
        result = b.commit(epoch, request_broadcast=self.request_broadcast)
        self.last_result = result
        ce = (result.get("epoch") or {}) if isinstance(result.get("epoch"), dict) else {}
        logger.info(
            f"Epoch committed root={(result.get('epoch_root') or '')[:16]}… "
            f"height={ce.get('height')} hash={(ce.get('block_hash') or '')[:12]}"
        )
        return result

    def _loop(self):
        self._stop.wait(min(30.0, self.interval / 10))
        while not self._stop.is_set():
            try:
                self.tick_once()
            except Exception as e:
                logger.warning(f"epoch tick failed: {e}")
            self._stop.wait(self.interval)


def start_epoch_ticker(comms: CommsLayer, **kwargs) -> EpochTicker:
    t = EpochTicker(comms, **kwargs)
    if os.getenv("AURORA_EPOCH_TICK", "0") in ("1", "true", "yes", "on"):
        t.start()
    return t
