"""Container entry: serve app; mount ops; never die on optional imports."""
from __future__ import annotations

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aurora-dashboard.ship")

from dashboard.dashboard import (  # noqa: E402
    app,
    bus,
    comms,
    get_anchor,
    get_fabric,
    get_identity,
    get_torrent_manager,
)

from fastapi.responses import JSONResponse  # noqa: E402

# Prefer full boot path
try:
    from dashboard.boot_ops import boot

    boot(
        app,
        get_comms=lambda: comms,
        get_torrent_manager=get_torrent_manager,
        get_anchor=get_anchor,
        get_identity=get_identity,
        get_fabric=get_fabric,
        bus=bus,
    )
except Exception as e:
    logger.exception(f"boot_ops failed: {e}")

mounted: list = []
try:
    from dashboard.mount_all import mount_optional_ops

    mounted = mount_optional_ops(
        app,
        get_comms=lambda: comms,
        get_torrent_manager=get_torrent_manager,
        get_anchor=get_anchor,
        get_identity=get_identity,
    ) or []
except Exception as e:
    logger.warning(f"mount_optional_ops: {e}")


def _has(path: str, method: str = "POST") -> bool:
    for r in app.routes:
        if getattr(r, "path", None) == path and method in (getattr(r, "methods", set()) or set()):
            return True
    return False


if not _has("/btc/identity/register", "POST"):

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

if not _has("/btc/status", "GET"):

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

# Open mint removed — explicit 410 if something still calls it
if not _has("/bvl/reward_seed", "POST"):

    @app.post("/bvl/reward_seed")
    async def _ship_bvl_reward_seed_blocked():
        return JSONResponse(
            {
                "ok": False,
                "error": "open mint disabled — BVL is earned via EconomyReactor (asset.complete / anchored)",
            },
            status_code=410,
        )

if not _has("/bvl/status", "GET"):

    @app.get("/bvl/status")
    def _ship_bvl_status():
        try:
            from mods.bvl.ledger_service import BabelLedger

            return {"status": "ok", **BabelLedger(comms).status()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


@app.get("/healthz")
def _ship_healthz():
    redis_ok = False
    try:
        redis_ok = bool(comms.r.ping())
    except Exception:
        pass
    return {
        "status": "healthy" if redis_ok else "degraded",
        "redis": redis_ok,
        "mounted": mounted,
        "node_id": comms.node_id,
    }


logger.info("ship ready")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
