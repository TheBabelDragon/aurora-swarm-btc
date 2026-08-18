"""Guaranteed /btc/identity/* routes — never drop register identity."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.identity_fix")


def _has(app: Any, path: str, method: str = "POST") -> bool:
    for r in app.routes:
        if getattr(r, "path", None) == path and method in (getattr(r, "methods", set()) or set()):
            return True
    return False


def install_identity_routes(
    app: Any,
    *,
    get_comms: Callable[[], Any],
    get_identity: Optional[Callable[[], Any]] = None,
):
    def _resolve_identity():
        if get_identity:
            try:
                ident = get_identity()
                if ident:
                    return ident
            except Exception as e:
                logger.warning(f"get_identity: {e}")
        # Direct fallback — never fail open on wrong import names
        from mods.btc_identity.identity import NodeIdentity

        return NodeIdentity(get_comms())

    if not _has(app, "/btc/identity/register", "POST"):

        @app.post("/btc/identity/register")
        async def btc_identity_register_fixed():
            try:
                ident = _resolve_identity()
                ident.register_with_identity(
                    capabilities=["dashboard", "btc_identity", "mesh", "chat"]
                )
                return {"status": "ok", "identity": ident.identity_view()}
            except Exception as e:
                logger.exception("identity register")
                return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

        logger.info("installed /btc/identity/register")

    if not _has(app, "/btc/identity/status", "GET"):

        @app.get("/btc/identity/status")
        def btc_identity_status():
            try:
                ident = _resolve_identity()
                return {"status": "ok", "identity": ident.identity_view()}
            except Exception as e:
                return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    # Always override broken handler if present by adding a second path alias
    @app.post("/btc/identity/register_safe")
    async def btc_identity_register_safe():
        try:
            ident = _resolve_identity()
            ident.register_with_identity(
                capabilities=["dashboard", "btc_identity", "mesh", "chat"]
            )
            return {"status": "ok", "identity": ident.identity_view()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    logger.info("identity_fix ready")
