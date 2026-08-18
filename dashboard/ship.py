"""Container entry: import app, force-mount all ops routers."""
from __future__ import annotations

import logging

logger = logging.getLogger("aurora-dashboard.ship")

from dashboard.dashboard import (  # noqa: E402
    app,
    comms,
    get_anchor,
    get_fabric,
    get_identity,
    get_torrent_manager,
)

try:
    from dashboard.mount_all import mount_optional_ops

    mounted = mount_optional_ops(
        app,
        get_comms=lambda: comms,
        get_torrent_manager=get_torrent_manager,
        get_anchor=get_anchor,
        get_identity=get_identity,
    )
    logger.info(f"ship mounted: {mounted}")
except Exception as e:
    logger.exception(f"ship mount_optional_ops failed: {e}")

if __name__ == "__main__":
    import uvicorn

    get_torrent_manager()
    get_anchor()
    get_fabric()
    get_identity()
    uvicorn.run(app, host="0.0.0.0", port=8000)
