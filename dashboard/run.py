"""Uvicorn target: dashboard.run:app — unique node id + mesh register."""
from __future__ import annotations

from dashboard.dashboard import (
    app,
    bus,
    comms,
    get_anchor,
    get_fabric,
    get_identity,
    get_torrent_manager,
)

# Ensure this machine is not anonymously "dashboard" on a multi-node LAN
try:
    from comms.node_id import default_node_id

    nid = default_node_id("node")
    if comms.node_id in ("dashboard", "unknown-node", "unknown") or not comms.node_id:
        comms.node_id = nid
    else:
        # still allow hostname-uniquify if both set to same env by mistake
        pass
    # Prefer env/hostname identity always when AURORA_NODE_ID unset
    import os

    if not (os.getenv("AURORA_NODE_ID") or "").strip():
        comms.node_id = nid
    comms.register_node(
        node_type="dashboard",
        capabilities=["dashboard", "mesh", "mining_engine"],
        metadata={"role": "dashboard"},
    )
    comms.heartbeat(metadata={"status": "online"})
except Exception:
    pass

from dashboard.boot_ops import boot

boot(
    app,
    get_comms=lambda: comms,
    get_torrent_manager=get_torrent_manager,
    get_anchor=get_anchor,
    get_identity=get_identity,
    get_fabric=get_fabric,
    bus=bus,
)

try:
    get_torrent_manager()
except Exception:
    pass

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
