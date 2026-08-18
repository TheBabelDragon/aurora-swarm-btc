"""Container entry: import app, force-mount ops, fallback identity/BVL routes."""
from __future__ import annotations

import logging

from fastapi import Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.ship")

from dashboard.dashboard import (  # noqa: E402
    app,
    comms,
    get_anchor,
    get_fabric,
    get_identity,
    get_torrent_manager,
)

# Primary: mount all ops modules
try:
    from dashboard.mount_all import mount_optional_ops

    mounted = mount_optional_ops(
        app,
        get_comms=lambda: comms,
        get_torrent_manager=get_torrent_manager,
        get_anchor=get_anchor,
        get_identity=get_identity,
    )
    logger.info(f"ship mounted: {mounted}")
except Exception as e:
    logger.exception(f"ship mount_optional_ops failed: {e}")
    mounted = []


def _route_exists(path: str, method: str = "POST") -> bool:
    for r in app.routes:
        if getattr(r, "path", None) == path and method in (getattr(r, "methods", None) or set()):
            return True
    return False


# Fallback routes if mount_all did not attach them (fixes Not Found on UI buttons)
if not _route_exists("/btc/identity/register", "POST"):

    @app.post("/btc/identity/register")
    async def _ship_identity_register():
        try:
            ident = get_identity()
            if not ident:
                return JSONResponse(
                    {"status": "error", "detail": "btc_identity unavailable"},
                    status_code=400,
                )
            ident.register_with_identity(capabilities=["dashboard", "btc_identity"])
            return {"status": "ok", "identity": ident.identity_view()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    logger.info("ship fallback: /btc/identity/register")

if not _route_exists("/btc/status", "GET"):

    @app.get("/btc/status")
    def _ship_btc_status():
        import os

        identity = None
        try:
            ident = get_identity()
            if ident:
                identity = ident.identity_view()
        except Exception as e:
            identity = {"error": str(e)}
        return {
            "network": os.getenv("AURORA_BTC_NETWORK", "signet"),
            "identity": identity,
            "anchor_ready": get_anchor() is not None,
        }

    logger.info("ship fallback: /btc/status")

if not _route_exists("/bvl/reward_seed", "POST"):

    @app.post("/bvl/reward_seed")
    async def _ship_bvl_reward_seed(
        asset_id: str = Form(""),
        node_id: str = Form(None),
    ):
        try:
            from mods.bvl.ledger_service import BabelLedger

            bvl = BabelLedger(comms)
            nid = (node_id or "").strip() or comms.node_id
            return bvl.reward_seed(nid, asset_id=(asset_id or "").strip() or "genesis")
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    logger.info("ship fallback: /bvl/reward_seed")

if not _route_exists("/bvl/status", "GET"):

    @app.get("/bvl/status")
    def _ship_bvl_status():
        try:
            from mods.bvl.ledger_service import BabelLedger

            return {"status": "ok", **BabelLedger(comms).status()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    logger.info("ship fallback: /bvl/status")


if __name__ == "__main__":
    import uvicorn

    get_torrent_manager()
    get_anchor()
    get_fabric()
    get_identity()
    uvicorn.run(app, host="0.0.0.0", port=8000)
