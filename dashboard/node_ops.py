"""Per-node command center — target a specific mesh peer."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from fastapi import Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.node_ops")


def install_node_ops(app: Any, *, get_comms: Callable[[], Any], get_identity: Optional[Callable[[], Any]] = None):
    @app.get("/comms/node/{node_id}")
    def node_detail(node_id: str):
        comms = get_comms()
        node_id = (node_id or "").strip()
        peers = { (n.get("node_id") or ""): n for n in (comms.get_active_nodes() or []) }
        info = peers.get(node_id) or {"node_id": node_id, "online": False}
        meta = info.get("metadata") or {}
        hashrate = {}
        try:
            st = comms.get_state(f"worker:{node_id}:hashrate")
            if isinstance(st, dict):
                hashrate = st
        except Exception:
            pass
        bvl_bal = 0.0
        try:
            from mods.bvl.ledger_service import BabelLedger

            bvl_bal = BabelLedger(comms).balance(node_id)
        except Exception:
            pass
        identity = None
        try:
            identity = comms.get_state(f"node:identity:{node_id}")
        except Exception:
            pass
        return {
            "ok": True,
            "node_id": node_id,
            "online": node_id in peers,
            "info": info,
            "metadata": meta,
            "hashrate": hashrate,
            "bvl_balance": bvl_bal,
            "identity": identity,
            "ts": time.time(),
        }

    @app.post("/comms/node/{node_id}/command")
    async def node_command(
        node_id: str,
        action: str = Form(...),
        factor: Optional[float] = Form(None),
        intensity: Optional[str] = Form(None),
        reason: str = Form("node_command_center"),
        message: str = Form(""),
    ):
        comms = get_comms()
        node_id = (node_id or "").strip()
        action = (action or "").strip().lower()
        if not node_id or not action:
            return JSONResponse({"ok": False, "error": "node_id and action required"}, status_code=400)

        body = {"action": action, "reason": reason, "from": comms.node_id}
        if factor is not None:
            body["factor"] = factor
        if intensity is not None:
            body["intensity"] = intensity

        try:
            if action == "chat":
                from comms.chat import MeshChat

                text = (message or "").strip() or f"[cmd] ping from {comms.node_id}"
                out = MeshChat(comms).send(text, to=node_id)
                return {"ok": True, "action": "chat", "target": node_id, "result": out}

            if action == "bvl_balance":
                from mods.bvl.ledger_service import BabelLedger

                return {
                    "ok": True,
                    "action": action,
                    "target": node_id,
                    "balance": BabelLedger(comms).balance(node_id),
                }

            # mining / fleet commands
            comms.send_to_node(node_id, body)
            # also publish worker command channel used by engines
            try:
                from comms.layer import SwarmMessage

                comms.publish_message(
                    f"command.node.{node_id}",
                    SwarmMessage(type="command", payload=body, source=comms.node_id, target=node_id),
                )
            except Exception:
                pass
            return {"ok": True, "action": action, "target": node_id, "payload": body}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/comms/global")
    def global_stats():
        """Live collective snapshot — compute + BVL on shared Redis."""
        comms = get_comms()
        peers = comms.get_active_nodes() or []
        total_hs = 0.0
        for n in peers:
            nid = n.get("node_id") or ""
            meta = n.get("metadata") or {}
            hs = meta.get("hashrate_hs")
            if hs is None:
                try:
                    st = comms.get_state(f"worker:{nid}:hashrate") or {}
                    hs = st.get("hashrate_hs") or float(st.get("hashrate_ghs") or 0) * 1e9
                except Exception:
                    hs = 0
            total_hs += float(hs or 0)

        bvl = {"supply": 0, "balances_global": {}, "balance_sum": 0}
        try:
            from mods.bvl.ledger_service import BabelLedger

            bvl = BabelLedger(comms).status()
        except Exception as e:
            bvl["error"] = str(e)

        identity = None
        try:
            if get_identity:
                ident = get_identity()
                if ident:
                    identity = ident.identity_view()
        except Exception:
            pass

        return {
            "ok": True,
            "node_id": comms.node_id,
            "peer_count": len(peers),
            "peers": [p.get("node_id") for p in peers],
            "global_hashrate_hs": total_hs,
            "global_hashrate_display": _fmt(total_hs),
            "bvl": bvl,
            "identity": identity,
            "ts": time.time(),
        }

    logger.info("node_ops mounted")


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
