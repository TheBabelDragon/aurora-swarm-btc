"""Mount BVL/BTC/fabric/mining once when dashboard.dashboard loads."""
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
        logger.warning(f"mount_all failed, trying direct: {e}")
        for name, kwargs in [
            ("bvl_ops", {"get_comms": get_comms}),
            ("btc_ops", {"get_anchor": get_anchor, "get_identity": get_identity}),
        ]:
            try:
                try:
                    mod = __import__(f"dashboard.{name}", fromlist=["*"])
                except Exception:
                    mod = __import__(name)
                if name == "bvl_ops":
                    mod.mount_bvl_ops(app, **kwargs)
                else:
                    mod.mount_btc_ops(app, **kwargs)
                logger.info(f"direct mount {name} ok")
            except Exception as e2:
                logger.warning(f"direct mount {name}: {e2}")
    app.state.aurora_booted = True
