"""Dashboard routes for Babel Value Ledger."""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.bvl")


def mount_bvl_ops(app: FastAPI, *, get_comms: Callable[[], Any]):
    def _ledger():
        from mods.bvl.ledger_service import BabelLedger

        return BabelLedger(get_comms())

    @app.get("/bvl/status")
    def bvl_status():
        try:
            return {"status": "ok", **_ledger().status()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/bvl/ledger")
    def bvl_ledger(limit: int = 30):
        try:
            return {"items": _ledger().recent(limit)}
        except Exception as e:
            return {"items": [], "error": str(e)}

    @app.post("/bvl/reward_seed")
    async def bvl_reward_seed(asset_id: str = Form(""), node_id: str = Form(None)):
        try:
            bvl = _ledger()
            if node_id and node_id.strip():
                return bvl.reward_seed(node_id.strip(), asset_id=asset_id.strip())
            if asset_id.strip():
                return {"status": "ok", "results": bvl.score_holders(asset_id.strip())}
            return bvl.reward_seed(asset_id=asset_id.strip())
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/bvl/reward_attest")
    async def bvl_reward_attest(asset_id: str = Form("")):
        try:
            return _ledger().reward_attest(asset_id=asset_id.strip())
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/bvl/transfer")
    async def bvl_transfer(to_node: str = Form(...), amount: float = Form(...), memo: str = Form("")):
        try:
            return _ledger().transfer(to_node.strip(), float(amount), memo=memo)
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/bvl/settle")
    async def bvl_settle(amount: float = Form(...), tip_node: str = Form(None), asset_id: str = Form("")):
        try:
            return _ledger().settle_to_sats(
                float(amount),
                tip_node=(tip_node.strip() if tip_node else None),
                asset_id=asset_id.strip(),
            )
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/bvl/attest_supply")
    async def bvl_attest_supply():
        try:
            from mods.bvl.economy import EconomyReactor

            reactor = EconomyReactor(get_comms())
            return reactor.attest_supply()
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    logger.info("bvl_ops routes mounted")
