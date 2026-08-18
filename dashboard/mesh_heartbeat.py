"""Keep this node visible on the shared Redis mesh."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("aurora-dashboard.mesh_hb")


def start_mesh_heartbeat(get_comms: Callable[[], Any], interval: float = 20.0):
    def _loop():
        while True:
            try:
                comms = get_comms()
                comms.register_node(
                    node_type="dashboard",
                    capabilities=["dashboard", "mesh", "mining_engine"],
                    metadata={"role": "dashboard"},
                )
                comms.heartbeat(metadata={"status": "online"})
            except Exception as e:
                logger.debug(f"mesh heartbeat: {e}")
            time.sleep(interval)

    threading.Thread(target=_loop, name="mesh-heartbeat", daemon=True).start()
    logger.info("mesh heartbeat started")
