"""Attach optional ops routers (package-safe imports)."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("aurora-dashboard.mount")


def _import_mount(name: str):
    """Prefer package import; fall back to bare (PYTHONPATH=/app/dashboard)."""
    try:
        mod = __import__(f"dashboard.{name}", fromlist=["*"])
        return mod
    except Exception:
        mod = __import__(name)
        return mod


def mount_optional_ops(
    app: Any,
    *,
    get_comms: Callable[[], Any],
    get_torrent_manager: Optional[Callable[[], Any]] = None,
    get_anchor: Optional[Callable[[], Any]] = None,
    get_identity: Optional[Callable[[], Any]] = None,
):
    mounted = []

    try:
        m = _import_mount("fabric_ops")
        m.mount_fabric_ops(app, get_comms=get_comms, get_torrent_manager=get_torrent_manager)
        mounted.append("fabric")
    except Exception as e:
        logger.warning(f"fabric_ops: {e}")

    try:
        m = _import_mount("mining_ops")
        m.mount_mining_ops(app, get_comms=get_comms)
        mounted.append("mining")
    except Exception as e:
        logger.warning(f"mining_ops: {e}")

    try:
        m = _import_mount("bvl_ops")
        m.mount_bvl_ops(app, get_comms=get_comms)
        mounted.append("bvl")
    except Exception as e:
        logger.warning(f"bvl_ops: {e}")

    try:
        m = _import_mount("btc_ops")
        m.mount_btc_ops(app, get_anchor=get_anchor, get_identity=get_identity)
        mounted.append("btc")
    except Exception as e:
        logger.warning(f"btc_ops: {e}")

    logger.info(f"optional ops mounted: {mounted or 'NONE'}")
    return mounted
