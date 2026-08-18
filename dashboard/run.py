"""Uvicorn target — mining routes first so Start/Stop never wait on boot."""
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

# Mining FIRST — independent of mesh/boot
try:
    from dashboard.mining_engine_ops import install_mining_engine_ops

    install_mining_engine_ops(app, get_comms=lambda: comms)
except Exception as e:
    import logging

    logging.getLogger("aurora-dashboard").error(f"mining routes failed: {e}")

try:
    from comms.node_id import default_node_id
    import os

    nid = default_node_id("node")
    if not (os.getenv("AURORA_NODE_ID") or "").strip():
        comms.node_id = nid
    elif comms.node_id in ("dashboard", "unknown-node", "unknown") or not comms.node_id:
        comms.node_id = nid
    try:
        comms.register_node(
            node_type="dashboard",
            capabilities=["dashboard", "mesh", "mining_engine"],
            metadata={"role": "dashboard"},
        )
        comms.heartbeat(metadata={"status": "online"})
    except Exception:
        pass
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

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
