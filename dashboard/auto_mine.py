"""Start mining automatically with retries until hashrate or hard fail."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("aurora-dashboard.auto_mine")


def auto_mine_enabled() -> bool:
    return os.getenv("AURORA_AUTO_MINE", "1").lower() not in ("0", "false", "no", "off")


def start_auto_mine(get_comms: Callable[[], Any], delay: float = 2.0):
    if not auto_mine_enabled():
        logger.info("AURORA_AUTO_MINE disabled")
        return

    def _run():
        time.sleep(delay)
        for attempt in range(1, 6):
            try:
                from dashboard.local_miner import local_status, start_local

                comms = get_comms()
                st = local_status(comms)
                if st.get("running") and float(st.get("hashrate_hs") or 0) > 0:
                    logger.info("auto-mine: already hashing")
                    return
                out = start_local(comms)
                logger.info(
                    "auto-mine attempt %s ok=%s backend=%s err=%s",
                    attempt,
                    out.get("ok"),
                    out.get("backend"),
                    out.get("error"),
                )
                try:
                    comms.broadcast_to_workers({"action": "resume"})
                except Exception:
                    pass
                # wait for first rate sample
                time.sleep(5)
                st2 = local_status(comms)
                hs = float(st2.get("hashrate_hs") or 0)
                logger.info("auto-mine rate after start: %s H/s display=%s", hs, st2.get("hashrate_display"))
                if out.get("ok") and (hs > 0 or st2.get("running")):
                    return
            except Exception as e:
                logger.warning(f"auto-mine attempt {attempt}: {e}")
            time.sleep(3)

    threading.Thread(target=_run, name="auto-mine", daemon=True).start()
    logger.info("auto-mine scheduled with retries")
