"""Mount ops — additive; auto paths so UI never needs curl."""
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

    # Apply mining guards before any auto-mine
    try:
        from mods.mining_engine.stratum_guard import apply_stratum_guards

        apply_stratum_guards()
    except Exception as e:
        logger.warning(f"stratum_guard: {e}")

    try:
        from dashboard.html_fix import install_html_fix

        install_html_fix(app)
    except Exception as e:
        logger.warning(f"html_fix: {e}")

    try:
        from dashboard.identity_fix import install_identity_routes

        install_identity_routes(app, get_comms=get_comms, get_identity=get_identity)
    except Exception as e:
        logger.warning(f"identity_fix: {e}")

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

    try:
        from dashboard.comms_ops import install_comms_ops

        install_comms_ops(app, get_comms=get_comms)
    except Exception as e:
        logger.warning(f"comms_ops: {e}")

    try:
        from dashboard.node_ops import install_node_ops

        install_node_ops(app, get_comms=get_comms, get_identity=get_identity)
    except Exception as e:
        logger.warning(f"node_ops: {e}")

    try:
        from dashboard.selftest_ops import install_selftest_ops

        install_selftest_ops(app, get_comms=get_comms, get_identity=get_identity)
    except Exception as e:
        logger.warning(f"selftest_ops: {e}")

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
        from dashboard.mining_coins_ops import install_mining_coins_ops

        install_mining_coins_ops(app, get_comms=get_comms)
    except Exception as e:
        logger.warning(f"mining_coins_ops: {e}")

    try:
        from dashboard.status_live import install_status_live

        install_status_live(app, get_comms=get_comms, bus=bus)
    except Exception as e:
        logger.warning(f"status_live: {e}")

    try:
        from mods.bvl.economy import start_economy

        start_economy(get_comms())
    except Exception as e:
        logger.warning(f"economy reactor: {e}")

    try:
        from dashboard.auto_mine import start_auto_mine

        start_auto_mine(get_comms)
    except Exception as e:
        logger.warning(f"auto_mine: {e}")

    try:
        from dashboard.mesh_heartbeat import start_mesh_heartbeat

        start_mesh_heartbeat(get_comms)
    except Exception as e:
        logger.warning(f"mesh_heartbeat: {e}")

    try:
        from dashboard.stability import start_stability_loop

        start_stability_loop(get_comms)
    except Exception as e:
        logger.warning(f"stability: {e}")

    # Auto identity on process start (no button / no curl)
    try:
        from mods.btc_identity.identity import NodeIdentity

        ident = None
        if get_identity:
            try:
                ident = get_identity()
            except Exception:
                ident = None
        if not ident:
            ident = NodeIdentity(get_comms())
        ident.register_with_identity(
            capabilities=["dashboard", "mesh", "mining_engine", "chat", "btc_identity"]
        )
        logger.info("auto identity registered at boot")
    except Exception as e:
        logger.warning(f"auto identity: {e}")

    app.state.aurora_booted = True
