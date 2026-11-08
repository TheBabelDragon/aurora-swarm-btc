"""Mount Conflux into the Aurora dashboard application.

Process-local singleton ConfluxService.
Mount create_conflux_router exactly once.
Optional integration failures are reported; never silently claim operational.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("aurora-dashboard.conflux")

_service = None
_mounted = False
_mount_error: Optional[str] = None
_registration: Optional[dict] = None


def get_conflux_service():
    """Process-local singleton."""
    global _service
    if _service is None:
        from conflux.service import ConfluxService
        from conflux.config import ConfluxConfig

        _service = ConfluxService(config=ConfluxConfig.from_env())
        logger.info("ConfluxService singleton created")
    return _service


def conflux_mount_status() -> dict:
    return {
        "mounted": _mounted,
        "error": _mount_error,
        "registration": _registration,
        "service": get_conflux_service().status() if _mounted else None,
    }


def mount_conflux_ops(app: Any) -> bool:
    """Mount /conflux/* routes once. Returns True on success."""
    global _mounted, _mount_error, _registration

    if _mounted or getattr(app.state, "conflux_mounted", False):
        logger.info("conflux already mounted — skip")
        return True

    try:
        from conflux.routes import create_conflux_router

        router = create_conflux_router(get_conflux_service)
        app.include_router(router)
        app.state.conflux_mounted = True
        _mounted = True
        _mount_error = None
        logger.info("conflux routes mounted at /conflux/*")
    except Exception as e:
        _mount_error = str(e)
        _mounted = False
        logger.warning("conflux mount failed: %s", e)
        return False

    # Control plane registration (non-fatal)
    try:
        from conflux.control_registration import register_with_control_plane

        _registration = register_with_control_plane()
        if not _registration.get("ok"):
            logger.warning("conflux control registration: %s", _registration.get("error"))
    except Exception as e:
        _registration = {"ok": False, "error": str(e)}
        logger.warning("conflux control registration failed: %s", e)

    # Status endpoint for mount health
    @app.get("/conflux-mount/status")
    def _mount_status():
        return conflux_mount_status()

    return True
