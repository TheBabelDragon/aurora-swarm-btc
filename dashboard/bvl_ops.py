"""Dashboard routes for Babel Value Ledger — read + transfer, no open mint."""

from __future__ import annotations

import logging
import os
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

    # NOTE: /bvl/reward_seed and /bvl/reward_attest intentionally removed.
    # Minting is performed only by EconomyReactor on verified swarm events.

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

    @app.post("/bvl/genesis")
    async def bvl_genesis():
        """One-time bootstrap only when explicitly enabled and supply is zero."""
        if os.getenv("AURORA_BVL_ALLOW_GENESIS", "").lower() not in ("1", "true", "yes"):
            return JSONResponse(
                {
                    "ok": False,
                    "error": "open mint disabled — set AURORA_BVL_ALLOW_GENESIS=1 for one-time bootstrap only",
                },
                status_code=403,
            )
        try:
            led = _ledger()
            if led.supply() > 0:
                return JSONResponse(
                    {"ok": False, "error": "genesis already used (supply > 0)", "supply": led.supply()},
                    status_code=409,
                )
            return led.reward_seed(led.node_id, asset_id="genesis", amount=None, force_system=True)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    logger.info("bvl_ops routes mounted (no open mint)")
