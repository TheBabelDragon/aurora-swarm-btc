"""Boot mining once — never overrides a user Stop."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("aurora-dashboard.auto_mine")


def auto_mine_enabled() -> bool:
    return os.getenv("AURORA_AUTO_MINE", "1").lower() not in ("0", "false", "no", "off")


def start_auto_mine(get_comms: Callable[[], Any], delay: float = 3.0):
    if not auto_mine_enabled():
        logger.info("AURORA_AUTO_MINE disabled")
        return

    def _run():
        time.sleep(delay)
        try:
            from dashboard.local_miner import is_user_stopped, local_status, start_local

            if is_user_stopped():
                logger.info("auto-mine skipped — user stopped")
                return
            comms = get_comms()
            st = local_status(comms)
            if st.get("running"):
                logger.info("auto-mine: already running")
                return
            out = start_local(comms)
            logger.info(
                "auto-mine ok=%s running=%s display=%s",
                out.get("ok"),
                out.get("running"),
                out.get("hashrate_display"),
            )
        except Exception as e:
            logger.warning(f"auto-mine failed: {e}")

    threading.Thread(target=_run, name="auto-mine", daemon=True).start()
    logger.info("auto-mine scheduled (single attempt, respects Stop)")
