"""Comms Layer — mesh status, discovery, export, live chat."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional

from fastapi import Form, Query
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger("aurora-dashboard.comms_ops")


def _redact_redis(url: str) -> str:
    if not url:
        return ""
    if "@" in url:
        return url.split("@", 1)[0].split("://")[0] + "://***@" + url.split("@", 1)[1]
    return url


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


def install_comms_ops(app: Any, *, get_comms: Callable[[], Any]):
    def _chat():
        from comms.chat import MeshChat

        return MeshChat(get_comms())

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

        total_hs = 0.0
        for n in peers:
            nid = n.get("node_id") or ""
            meta = n.get("metadata") or {}
            hs = meta.get("hashrate_hs")
            if hs is None:
                try:
                    st = comms.get_state(f"worker:{nid}:hashrate")
                    if isinstance(st, dict):
                        hs = st.get("hashrate_hs") or float(st.get("hashrate_ghs") or 0) * 1e9
                except Exception:
                    hs = None
            if hs:
                total_hs += float(hs)

        lan = []
        try:
            from comms.discovery import get_discovery

            d = get_discovery()
            if d:
                lan = d.snapshot_peers()
        except Exception:
            pass

        return {
            "status": "ok",
            "redis_ok": redis_ok,
            "redis_url": _redact_redis(getattr(comms, "redis_url", "") or os.getenv("REDIS_URL", "")),
            "node_id": comms.node_id,
            "peer_count": len(peers),
            "peers": peers,
            "lan_discovered": lan,
            "lan_count": len(lan),
            "global_hashrate_hs": total_hs,
            "global_hashrate_display": _fmt(total_hs),
            "discovery_port": int(os.getenv("AURORA_DISCOVERY_PORT", "7379") or 7379),
            "ts": time.time(),
        }

    @app.get("/comms/export")
    def comms_export():
        try:
            from comms.mesh_export import export_join_pack
            from comms.discovery import get_discovery

            comms = get_comms()
            d = get_discovery()
            return export_join_pack(
                node_id=comms.node_id,
                redis_url=getattr(comms, "redis_url", "") or os.getenv("REDIS_URL", ""),
                peers=comms.get_active_nodes() or [],
                discovered=d.snapshot_peers() if d else [],
            )
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/comms/export.env", response_class=PlainTextResponse)
    def comms_export_env():
        try:
            from comms.mesh_export import export_join_pack

            pack = export_join_pack(
                node_id=get_comms().node_id,
                redis_url=getattr(get_comms(), "redis_url", "") or os.getenv("REDIS_URL", ""),
            )
            return PlainTextResponse(pack["env_export"], media_type="text/plain")
        except Exception as e:
            return PlainTextResponse(f"# error: {e}\n", status_code=500)

    @app.get("/comms/export.sh", response_class=PlainTextResponse)
    def comms_export_sh():
        try:
            from comms.mesh_export import export_join_pack

            pack = export_join_pack(
                node_id=get_comms().node_id,
                redis_url=getattr(get_comms(), "redis_url", "") or os.getenv("REDIS_URL", ""),
            )
            script = (
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                + pack["env_export"]
                + "echo \"Joining mesh REDIS_URL=$REDIS_URL\"\n"
                + "docker compose -f docker-compose.solo.yml up -d --build\n"
            )
            return PlainTextResponse(script, media_type="text/x-shellscript")
        except Exception as e:
            return PlainTextResponse(f"#!/bin/false\n# error: {e}\n", status_code=500)

    @app.get("/comms/discovery")
    def comms_discovery():
        try:
            from comms.discovery import get_discovery

            d = get_discovery()
            if not d:
                return {"enabled": False, "peers": []}
            return {"enabled": True, "join_url": d.join_url, "port": d.port, "peers": d.snapshot_peers()}
        except Exception as e:
            return {"enabled": False, "error": str(e), "peers": []}

    @app.post("/comms/register")
    async def comms_register():
        try:
            comms = get_comms()
            comms.register_node(
                node_type="dashboard",
                capabilities=["dashboard", "mesh", "mining_engine", "comms", "chat"],
                metadata={"status": "online"},
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
            # also as swarm chat
            _chat().send(message, to=None)
            return {"ok": True, "published": True, "message": message}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    # —— Live chat ——
    @app.get("/comms/chat/users")
    def chat_users(q: str = Query("")):
        try:
            c = _chat()
            users = c.search_users(q) if q else c.list_users()
            return {"ok": True, "me": get_comms().node_id, "users": users, "count": len(users)}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/comms/chat/history")
    def chat_history(
        with_user: Optional[str] = Query(None),
        room: str = Query("swarm"),
        limit: int = Query(80),
    ):
        try:
            return {
                "ok": True,
                "me": get_comms().node_id,
                "with_user": with_user,
                "room": room if not with_user else None,
                "messages": _chat().history(with_user=with_user, room=room, limit=limit),
            }
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/comms/chat/send")
    async def chat_send(
        text: str = Form(...),
        to: str = Form(""),
        room: str = Form("swarm"),
    ):
        try:
            to_n = (to or "").strip() or None
            out = _chat().send(text, to=to_n, room=room or "swarm")
            if not out.get("ok"):
                return JSONResponse(out, status_code=400)
            return out
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/comms/chat/add_user")
    async def chat_add_user(node_id: str = Form(...), display: str = Form("")):
        try:
            nid = (node_id or "").strip()
            if not nid:
                return JSONResponse({"ok": False, "error": "node_id required"}, status_code=400)
            _chat().remember_user(nid, display=display or nid, source="external")
            return {"ok": True, "node_id": nid}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/comms/events")
    def comms_events(limit: int = 20):
        try:
            return {"items": get_comms().get_recent_events(limit)}
        except Exception as e:
            return {"items": [], "error": str(e)}

    logger.info("comms_ops mounted (chat+export+discovery)")
