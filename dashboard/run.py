"""Uvicorn target: dashboard.run:app with truthful status + ops mounted."""
from __future__ import annotations

from dashboard.dashboard import (
    app,
    comms,
    get_anchor,
    get_fabric,
    get_identity,
    get_torrent_manager,
)
from dashboard.boot_ops import boot

boot(
    app,
    get_comms=lambda: comms,
    get_torrent_manager=get_torrent_manager,
    get_anchor=get_anchor,
    get_identity=get_identity,
    get_fabric=get_fabric,
)

# Eager torrent manager so capability exists before first UI poll
try:
    get_torrent_manager()
except Exception:
    pass

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
