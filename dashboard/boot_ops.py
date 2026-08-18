"""Mount ops + live status + mining + BVL economy."""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("aurora-dashboard.boot")


def boot(
    app: Any,
    *,
    get_comms: Callable[[], Any],
    get_torrent_manager: Optional[Callable[[], Any]] = None,
    get_anchor: Optional[Callable[[], Any]] = None,
    get_identity: Optional[Callable[[], Any]] = None,
    get_fabric: Optional[Callable[[], Any]] = None,
    bus: Any = None,
):
    if getattr(app.state, "aurora_booted", False):
        return

    try:
        from dashboard.mount_all import mount_optional_ops

        mounted = mount_optional_ops(
            app,
            get_comms=get_comms,
            get_torrent_manager=get_torrent_manager,
            get_anchor=get_anchor,
            get_identity=get_identity,
        )
        logger.info(f"boot mounted: {mounted}")
    except Exception as e:
        logger.warning(f"mount_all failed: {e}")
        for name in ("bvl_ops", "btc_ops"):
            try:
                try:
                    mod = __import__(f"dashboard.{name}", fromlist=["*"])
                except Exception:
                    mod = __import__(name)
                if name == "bvl_ops":
                    mod.mount_bvl_ops(app, get_comms=get_comms)
                else:
                    mod.mount_btc_ops(app, get_anchor=get_anchor, get_identity=get_identity)
            except Exception as e2:
                logger.warning(f"{name}: {e2}")

    try:
        from dashboard.truth_routes import install_truth_routes

        install_truth_routes(
            app,
            get_comms=get_comms,
            get_torrent_manager=get_torrent_manager or (lambda: None),
            get_fabric=get_fabric or (lambda: None),
            get_anchor=get_anchor or (lambda: None),
        )
    except Exception as e:
        logger.warning(f"truth_routes: {e}")

    try:
        from dashboard.ops_native import install_ops_native

        install_ops_native(app, get_comms=get_comms)
    except Exception as e:
        logger.warning(f"ops_native: {e}")

    try:
        from dashboard.mining_engine_ops import install_mining_engine_ops

        install_mining_engine_ops(app, get_comms=get_comms)
    except Exception as e:
        logger.warning(f"mining_engine_ops: {e}")

    try:
        from dashboard.status_live import install_status_live

        # bus optional — pass from run.py if available
        install_status_live(app, get_comms=get_comms, bus=bus)
    except Exception as e:
        logger.warning(f"status_live: {e}")

    try:
        from mods.bvl.economy import start_economy

        start_economy(get_comms())
        logger.info("BVL EconomyReactor started")
    except Exception as e:
        logger.warning(f"economy reactor: {e}")

    app.state.aurora_booted = True
