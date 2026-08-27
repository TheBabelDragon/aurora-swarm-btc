"""Fleet + BVL + command routes — no second Mining UI inject.

home_template.html owns Start/Stop/status. Do not inject /ux/extra.js.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from fastapi import Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.ops_native")


def install_ops_native(app: Any, *, get_comms: Callable[[], Any]):
    # Intentionally NO HTML middleware / NO second Start-Stop panel.

    @app.get("/mesh/fleet")
    def mesh_fleet():
        comms = get_comms()
        nodes_out = []
        try:
            raw_nodes = comms.get_active_nodes() or []
        except Exception as e:
            return {"nodes": [], "error": str(e)}
        for n in raw_nodes:
            if not isinstance(n, dict):
                continue
            nid = n.get("node_id") or ""
            meta = n.get("metadata") or {}
            hr = meta.get("hashrate_ghs")
            hr_disp = meta.get("hashrate_display")
            hr_hs = meta.get("hashrate_hs")
            try:
                st = comms.get_state(f"worker:{nid}:hashrate")
                if isinstance(st, dict):
                    if st.get("hashrate_ghs") is not None:
                        hr = st.get("hashrate_ghs")
                    if st.get("hashrate_display"):
                        hr_disp = st.get("hashrate_display")
                    if st.get("hashrate_hs") is not None:
                        hr_hs = st.get("hashrate_hs")
            except Exception:
                pass
            nodes_out.append(
                {
                    "node_id": nid,
                    "hashrate_ghs": hr,
                    "hashrate_hs": hr_hs,
                    "hashrate_display": hr_disp,
                    "status": meta.get("status"),
                }
            )
        return {"nodes": nodes_out, "ts": time.time()}

    @app.get("/events")
    def events(limit: int = 20):
        try:
            return {"events": get_comms().get_recent_events(limit) or []}
        except Exception as e:
            return {"events": [], "error": str(e)}

    @app.post("/command/broadcast")
    async def command_broadcast(
        action: str = Form(...),
        factor: Optional[float] = Form(None),
        reason: str = Form("manual"),
    ):
        payload = {"action": action, "reason": reason}
        if factor is not None:
            payload["factor"] = factor
        try:
            get_comms().broadcast_to_workers(payload)
            return {"status": "sent", "action": action, "target": "all_workers"}
        except Exception as e:
            return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

    @app.post("/command/to_node/{node_id}")
    async def command_to_node(
        node_id: str,
        action: str = Form(...),
        factor: Optional[float] = Form(None),
        reason: str = Form("manual"),
    ):
        payload = {"action": action, "reason": reason}
        if factor is not None:
            payload["factor"] = factor
        try:
            get_comms().send_to_node(node_id, payload)
            return {"status": "sent", "action": action, "target": node_id}
        except Exception as e:
            return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

    @app.get("/metafield/status")
    def metafield_status():
        try:
            from mods.metafield_bridge.bridge import load_stats, snapshot_from_stats

            snap = snapshot_from_stats(load_stats())
            return {"ok": True, **snap}
        except Exception as e:
            return {"ok": False, "live": False, "health": "unavailable", "error": str(e)}

    @app.post("/bvl/transfer_safe")
    async def bvl_transfer_safe(
        to_node: str = Form(...),
        confirm_to: str = Form(...),
        amount: float = Form(...),
        memo: str = Form(""),
        require_known: str = Form(""),
    ):
        to_node = (to_node or "").strip()
        confirm_to = (confirm_to or "").strip()
        if not to_node or to_node != confirm_to:
            return JSONResponse({"ok": False, "error": "confirm must match"}, status_code=400)
        try:
            from mods.bvl.ledger_service import BabelLedger

            return BabelLedger(get_comms()).transfer(to_node, float(amount), memo=memo)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    logger.info("ops_native installed (fleet+commands+bvl+metafield, no dual mining UI)")
