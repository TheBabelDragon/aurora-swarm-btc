"""
Idempotent route bootstrap used by dashboard.py module load.
Safe if ship.py also mounts (FastAPI will error on duplicate routes —
we guard with a flag on app.state).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("aurora-dashboard.bootstrap")


def ensure_ops(
    app: Any,
    *,
    get_comms: Callable[[], Any],
    get_torrent_manager: Optional[Callable[[], Any]] = None,
    get_anchor: Optional[Callable[[], Any]] = None,
    get_identity: Optional[Callable[[], Any]] = None,
):
    if getattr(app.state, "aurora_ops_mounted", False):
        return getattr(app.state, "aurora_ops_list", [])
    try:
        from dashboard.mount_all import mount_optional_ops
    except Exception:
        try:
            from mount_all import mount_optional_ops
        except Exception as e:
            logger.warning(f"mount_all unavailable: {e}")
            return []

    mounted = mount_optional_ops(
        app,
        get_comms=get_comms,
        get_torrent_manager=get_torrent_manager,
        get_anchor=get_anchor,
        get_identity=get_identity,
    )
    app.state.aurora_ops_mounted = True
    app.state.aurora_ops_list = mounted
    return mounted
