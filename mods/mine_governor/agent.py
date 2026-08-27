"""Background agent: posture + inbox + last-applied history."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

from .apply import apply_command
from .history import last, record

logger = logging.getLogger("aurora.mine_governor.agent")


def _loadavg():
    try:
        return list(os.getloadavg())
    except Exception:
        return []


def posture(node_id: str) -> dict:
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
        "loadavg": _loadavg(),
        "running": bool(snap.get("running")),
        "hashrate_hs": snap.get("hashrate_hs") or 0,
        "hashrate_display": snap.get("hashrate_display"),
        "authorized": snap.get("authorized"),
        "wallet": snap.get("wallet"),
        "backend": snap.get("backend"),
        "governor": "mine_governor/0.2",
        "last_command": last(),
        "ts": time.time(),
    }


def _take(raw: dict) -> dict:
    action = str(raw.get("action") or "")
    extra = {k: v for k, v in raw.items() if k not in ("action", "_done", "_result", "from", "reason")}
    out = apply_command(action, **extra)
    record(action, out)
    return out


def start_governor(get_comms: Callable[[], Any], interval: float = 8.0) -> None:
    def _loop():
        while True:
            try:
                comms = get_comms()
                nid = getattr(comms, "node_id", None) or os.getenv("AURORA_NODE_ID") or "node"
                body = posture(nid)
                try:
                    comms.set_state(f"mining:worker:{nid}", body, expire=180)
                    comms.set_state(f"worker:{nid}:hashrate", body, expire=180)
                    comms.heartbeat(
                        metadata={
                            "mining": bool(body.get("running")),
                            "hashrate_hs": body.get("hashrate_hs") or 0,
                            "cpu_threads": body.get("cpu_threads"),
                            "governor": True,
                        }
                    )
                except Exception:
                    pass
                try:
                    raw = comms.get_state(f"minecmd:{nid}")
                except Exception:
                    raw = None
                if isinstance(raw, dict) and raw.get("action") and not raw.get("_done"):
                    out = _take(raw)
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
