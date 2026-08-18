"""Install optional ops routes once at process import time."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("aurora-dashboard.hooks")


def install(
    app: Any,
    *,
    get_comms: Callable[[], Any],
    get_torrent_manager: Optional[Callable[[], Any]] = None,
    get_anchor: Optional[Callable[[], Any]] = None,
    get_identity: Optional[Callable[[], Any]] = None,
):
    try:
        from mount_all import mount_optional_ops

        mount_optional_ops(
            app,
            get_comms=get_comms,
            get_torrent_manager=get_torrent_manager,
            get_anchor=get_anchor,
            get_identity=get_identity,
        )
        logger.info("app_hooks: mount_optional_ops installed")
    except Exception as e:
        logger.warning(f"app_hooks install failed: {e}")
