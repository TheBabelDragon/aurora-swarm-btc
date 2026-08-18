"""Comms Layer operations center — the testable mesh surface."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

from fastapi import Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.comms_ops")


def _redact_redis(url: str) -> str:
    if not url:
        return ""
    # redis://:pass@host:6379/0 → redis://***@host:6379/0
    if "@" in url:
        return url.split("@", 1)[0].split("://")[0] + "://***@" + url.split("@", 1)[1]
    return url


def install_comms_ops(app: Any, *, get_comms: Callable[[], Any]):
    @app.get("/comms/status")
    def comms_status():
        comms = get_comms()
        redis_ok = False
        try:
            redis_ok = bool(comms.ping()) if hasattr(comms, "ping") else bool(comms.r.ping())
        except Exception:
            redis_ok = False
        peers = []
        try:
            peers = comms.get_active_nodes() or []
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

        # Global compute snapshot from shared Redis
        total_hs = 0.0
        for n in peers:
            nid = n.get("node_id") or ""
            meta = n.get("metadata") or {}
            hs = meta.get("hashrate_hs")
            if hs is None:
                try:
                    st = comms.get_state(f"worker:{nid}:hashrate")
                    if isinstance(st, dict):
                        hs = st.get("hashrate_hs") or (
                            float(st.get("hashrate_ghs") or 0) * 1e9
                        )
                except Exception:
                    hs = None
            if hs:
                total_hs += float(hs)

        return {
            "status": "ok",
            "redis_ok": redis_ok,
            "redis_url": _redact_redis(getattr(comms, "redis_url", "") or os.getenv("REDIS_URL", "")),
            "node_id": comms.node_id,
            "peer_count": len(peers),
            "peers": [
                {
                    "node_id": p.get("node_id"),
                    "node_type": p.get("node_type"),
                    "capabilities": p.get("capabilities") or [],
                    "ts": p.get("ts"),
                    "metadata": p.get("metadata") or {},
                }
                for p in peers
            ],
            "global_hashrate_hs": total_hs,
            "global_hashrate_display": _fmt(total_hs),
            "ts": time.time(),
            "note": "Peers only appear when REDIS_URL is shared across machines",
        }

    @app.post("/comms/register")
    async def comms_register():
        try:
            comms = get_comms()
            comms.register_node(
                node_type="dashboard",
                capabilities=["dashboard", "mesh", "mining_engine", "comms"],
                metadata={"role": "dashboard", "status": "online"},
            )
            comms.heartbeat(metadata={"status": "online"})
            return {"ok": True, "node_id": comms.node_id, "peers": len(comms.get_active_nodes() or [])}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/comms/broadcast")
    async def comms_broadcast(message: str = Form("ping from dashboard")):
        try:
            from comms.layer import SwarmMessage

            comms = get_comms()
            msg = SwarmMessage(
                type="event.comms_test",
                payload={"text": message, "from": comms.node_id},
                source=comms.node_id,
            )
            comms.publish_message("events", msg)
            if hasattr(comms, "publish_event"):
                comms.publish_event("comms_test", {"text": message})
            return {"ok": True, "published": True, "message": message}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/comms/events")
    def comms_events(limit: int = 20):
        try:
            return {"items": get_comms().get_recent_events(limit)}
        except Exception as e:
            return {"items": [], "error": str(e)}

    logger.info("comms_ops mounted")


def _fmt(hs: float) -> str:
    if hs >= 1e12:
        return f"{hs/1e12:.3f} TH/s"
    if hs >= 1e9:
        return f"{hs/1e9:.3f} GH/s"
    if hs >= 1e6:
        return f"{hs/1e6:.2f} MH/s"
    if hs >= 1e3:
        return f"{hs/1e3:.2f} KH/s"
    return f"{hs:.0f} H/s"
