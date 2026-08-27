"""Background agent: publish posture + consume command inbox."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

from .apply import apply_command

logger = logging.getLogger("aurora.mine_governor.agent")


def _posture(node_id: str) -> dict:
    snap = {}
    try:
        from dashboard.mining_standalone import _snapshot

        snap = _snapshot() or {}
    except Exception:
        pass
    return {
        "node_id": node_id,
        "cpu_threads": int(os.getenv("AURORA_CPU_THREADS", "0") or 0),
        "cpus": os.cpu_count(),
        "running": bool(snap.get("running")),
        "hashrate_hs": snap.get("hashrate_hs") or 0,
        "hashrate_display": snap.get("hashrate_display"),
        "authorized": snap.get("authorized"),
        "wallet": snap.get("wallet"),
        "backend": snap.get("backend"),
        "governor": "mine_governor/0.1",
        "ts": time.time(),
    }


def start_governor(get_comms: Callable[[], Any], interval: float = 8.0) -> None:
    def _loop():
        while True:
            try:
                comms = get_comms()
                nid = getattr(comms, "node_id", None) or os.getenv("AURORA_NODE_ID") or "node"
                body = _posture(nid)
                try:
                    comms.set_state(f"mining:worker:{nid}", body, expire=180)
                    comms.set_state(f"worker:{nid}:hashrate", body, expire=180)
                    comms.heartbeat(metadata={
                        "mining": bool(body.get("running")),
                        "hashrate_hs": body.get("hashrate_hs") or 0,
                        "cpu_threads": body.get("cpu_threads"),
                    })
                except Exception:
                    pass
                # inbox: last command written by node_ops / scheduler
                try:
                    raw = comms.get_state(f"minecmd:{nid}")
                except Exception:
                    raw = None
                if isinstance(raw, dict) and raw.get("action") and not raw.get("_done"):
                    out = apply_command(str(raw.get("action")), **{k: v for k, v in raw.items() if k != "action"})
                    raw["_done"] = True
                    raw["_result"] = out
                    try:
                        comms.set_state(f"minecmd:{nid}", raw, expire=120)
                    except Exception:
                        pass
                    logger.info("governor applied %s → %s", raw.get("action"), out)
            except Exception as e:
                logger.debug("governor loop: %s", e)
            time.sleep(interval)

    threading.Thread(target=_loop, name="mine-governor", daemon=True).start()
    logger.info("mine_governor agent started")
