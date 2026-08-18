"""
Single place to attach optional ops routers.

Usage in dashboard.py:

    from mount_all import mount_optional_ops
    mount_optional_ops(app, get_comms=lambda: comms, get_torrent_manager=get_torrent_manager,
                       get_anchor=get_anchor, get_identity=get_identity)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("aurora-dashboard.mount")


def mount_optional_ops(
    app: Any,
    *,
    get_comms: Callable[[], Any],
    get_torrent_manager: Optional[Callable[[], Any]] = None,
    get_anchor: Optional[Callable[[], Any]] = None,
    get_identity: Optional[Callable[[], Any]] = None,
):
    try:
        from fabric_ops import mount_fabric_ops

        mount_fabric_ops(app, get_comms=get_comms, get_torrent_manager=get_torrent_manager)
    except Exception as e:
        logger.debug(f"fabric_ops: {e}")

    try:
        from mining_ops import mount_mining_ops

        mount_mining_ops(app, get_comms=get_comms)
    except Exception as e:
        logger.debug(f"mining_ops: {e}")

    try:
        from bvl_ops import mount_bvl_ops

        mount_bvl_ops(app, get_comms=get_comms)
    except Exception as e:
        logger.debug(f"bvl_ops: {e}")

    try:
        from btc_ops import mount_btc_ops

        mount_btc_ops(app, get_anchor=get_anchor, get_identity=get_identity)
    except Exception as e:
        logger.debug(f"btc_ops: {e}")

    logger.info("optional ops mount pass complete")
