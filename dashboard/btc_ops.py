"""
Extra Bitcoin-facing dashboard routes.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.btc")


def mount_btc_ops(
    app: FastAPI,
    *,
    get_anchor: Callable[[], Any],
    get_identity: Optional[Callable[[], Any]] = None,
):
    @app.post("/torrent/process_broadcasts_batched")
    async def process_broadcasts_batched():
        anc = get_anchor()
        if not anc:
            return JSONResponse({"status": "error", "detail": "btc_anchor not available"}, status_code=400)
        try:
            out = anc.process_queue_batched(max_items=32)
            return {"status": "ok", **out}
        except Exception as e:
            logger.exception("batch process failed")
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/btc/status")
    def btc_status():
        anc = get_anchor()
        pending = 0
        broadcaster = os.getenv("AURORA_BTC_BROADCASTER") or (
            "log" if os.getenv("AURORA_BTC_ANCHOR_BROADCAST") else "null"
        )
        if anc:
            try:
                pending = len(anc.queue.list_pending())
            except Exception:
                pass
        identity = None
        if get_identity:
            try:
                ident = get_identity()
                if ident:
                    identity = ident.identity_view()
            except Exception as e:
                identity = {"error": str(e)}
        return {
            "network": os.getenv("AURORA_BTC_NETWORK", "signet"),
            "broadcaster": broadcaster,
            "cli_send": os.getenv("AURORA_BTC_CLI_SEND", "") in ("1", "true", "yes"),
            "pending_broadcasts": pending,
            "mining_wallet": os.getenv(
                "MINING_WALLET", "bc1qdpqzuem4dkamt8ckcwaul7a2rhqju30xwn3f5g"
            ),
            "pool_url": os.getenv("POOL_URL", "stratum+tcp://stratum.braiins.com:3333"),
            "identity": identity,
            "anchor_ready": anc is not None,
        }

    @app.post("/btc/identity/register")
    async def btc_identity_register():
        if not get_identity:
            return JSONResponse({"status": "error", "detail": "identity not configured"}, status_code=400)
        try:
            ident = get_identity()
            if not ident:
                return JSONResponse({"status": "error", "detail": "btc_identity unavailable"}, status_code=400)
            ident.register_with_identity(capabilities=["dashboard", "btc_identity"])
            return {"status": "ok", "identity": ident.identity_view()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/ln/tip")
    async def ln_tip(asset_id: str = Form(...), node_id: str = Form(None)):
        anc = get_anchor()
        if not anc:
            return JSONResponse({"status": "error", "detail": "comms/anchor unavailable"}, status_code=400)
        try:
            from mods.ln_tips.service import TipService

            tips = TipService(anc.comms)
        except Exception as e:
            return JSONResponse({"status": "error", "detail": f"ln_tips unavailable: {e}"}, status_code=400)
        asset_id = asset_id.strip().lower()
        if node_id and str(node_id).strip():
            entry = tips.reward_seeder(asset_id, str(node_id).strip())
            return {"status": "ok", "tips": [entry]}
        entries = tips.reward_holders(asset_id)
        return {"status": "ok", "tips": entries}

    @app.get("/ln/tips")
    def ln_tips_recent(limit: int = 20):
        anc = get_anchor()
        if not anc:
            return {"items": []}
        from mods.ln_tips.service import TipService

        return {"items": TipService(anc.comms).recent(limit)}

    logger.info("btc_ops routes mounted")
