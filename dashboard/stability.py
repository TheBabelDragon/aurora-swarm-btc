"""
Lightweight stability helpers — additive only.
Re-registers mesh presence; does not stop mining or wipe state.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("aurora-dashboard.stability")


def start_stability_loop(get_comms: Callable[[], Any], interval: float = 30.0):
    def _loop():
        while True:
            try:
                comms = get_comms()
                # Soft presence only
                try:
                    comms.heartbeat(metadata={"status": "online", "stability": True})
                except Exception as e:
                    logger.debug(f"heartbeat: {e}")
                # Ensure stratum guards stay applied (noop if already)
                try:
                    from mods.mining_engine.stratum_guard import apply_stratum_guards

                    apply_stratum_guards()
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"stability loop: {e}")
            time.sleep(interval)

    threading.Thread(target=_loop, name="stability", daemon=True).start()
    logger.info("stability loop started")
