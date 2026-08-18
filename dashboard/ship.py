"""Optional entry: ensures mount_all before serving."""
from __future__ import annotations

from dashboard.dashboard import (
    app,
    comms,
    get_anchor,
    get_fabric,
    get_identity,
    get_torrent_manager,
)

try:
    from dashboard.mount_all import mount_optional_ops

    mount_optional_ops(
        app,
        get_comms=lambda: comms,
        get_torrent_manager=get_torrent_manager,
        get_anchor=get_anchor,
        get_identity=get_identity,
    )
except Exception as e:
    import logging

    logging.getLogger("aurora-dashboard.ship").warning(f"mount_optional_ops: {e}")

if __name__ == "__main__":
    import uvicorn

    get_torrent_manager()
    get_anchor()
    get_fabric()
    get_identity()
    uvicorn.run(app, host="0.0.0.0", port=8000)
