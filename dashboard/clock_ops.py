"""Dashboard routes for the artifact clock — Asset Fabric ↔ BTC Anchor."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.clock")


def mount_clock_ops(
    app: FastAPI,
    *,
    get_comms: Callable[[], Any],
    get_torrent_manager: Optional[Callable[[], Any]] = None,
    get_anchor: Optional[Callable[[], Any]] = None,
):
    def _fabric():
        from mods.asset_fabric.fabric import AssetFabric

        comms = get_comms()
        tm = get_torrent_manager() if get_torrent_manager else None
        anc = get_anchor() if get_anchor else None
        chain = getattr(anc, "chain", None) if anc else None
        fab = AssetFabric(comms, transport=tm, chain=chain)
        if anc:
            fab._anchor = anc
            fab._anchor_tried = True
        return fab

    @app.get("/fabric/clock/assets")
    def clock_assets():
        try:
            fab = _fabric()
            rows = []
            for row in fab.list_assets():
                clock = row.get("clock") or {}
                rows.append(
                    {
                        "asset_id": row.get("asset_id"),
                        "name": row.get("name"),
                        "pieces": f"{row.get('have', 0)}/{row.get('total', 0)}",
                        "have": row.get("have"),
                        "total": row.get("total"),
                        "possession": row.get("possession_state"),
                        "epoch": clock.get("epoch"),
                        "btc_height": clock.get("btc_height"),
                        "anchor_status": clock.get("confidence"),
                        "confirmations": (row.get("anchor") or {}).get("confirmations"),
                        "canonical": clock.get("confidence") == "confirmed",
                        "reorged": clock.get("confidence") == "reorged",
                        "anchor_id": clock.get("anchor_id"),
                        "manifest_hash": row.get("manifest_hash"),
                    }
                )
            tip = fab.current_clock()
            return {"status": "ok", "assets": rows, "chain": tip}
        except Exception as e:
            logger.exception("clock assets")
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/fabric/clock/{asset_id}")
    def clock_one(asset_id: str):
        try:
            fab = _fabric()
            c = fab.get_clock(asset_id.strip())
            return {"status": "ok", "clock": c.to_dict(), "possession": fab.possession(asset_id.strip())}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/fabric/history/{asset_id}")
    def clock_history(asset_id: str):
        try:
            fab = _fabric()
            return {"status": "ok", "history": fab.get_history(asset_id.strip())}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/fabric/anchor")
    async def clock_anchor(asset_id: str = Form(...)):
        try:
            fab = _fabric()
            rec = fab.anchor_asset(asset_id.strip())
            return {"status": "ok", "anchor": rec, "clock": fab.get_clock(asset_id.strip()).to_dict()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/fabric/verify")
    async def clock_verify(asset_id: str = Form(...)):
        try:
            fab = _fabric()
            return {"status": "ok", **fab.verify_anchor(asset_id.strip())}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/fabric/chain")
    def clock_chain():
        try:
            fab = _fabric()
            return {"status": "ok", "chain": fab.current_clock()}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    logger.info("clock_ops routes mounted")
