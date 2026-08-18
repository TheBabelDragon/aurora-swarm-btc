"""Keep node visible + start LAN discovery beacon."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("aurora-dashboard.mesh_hb")


def start_mesh_heartbeat(get_comms: Callable[[], Any], interval: float = 20.0):
    # Discovery + export surface
    try:
        from comms.discovery import start_discovery

        comms = get_comms()
        start_discovery(
            node_id=comms.node_id,
            redis_url=getattr(comms, "redis_url", "") or "",
            capabilities=["dashboard", "mesh", "mining_engine", "comms"],
        )
    except Exception as e:
        logger.warning(f"discovery start: {e}")

    def _loop():
        while True:
            try:
                comms = get_comms()
                meta = {"status": "online"}
                try:
                    from dashboard.local_miner import local_status

                    st = local_status(comms)
                    if st.get("hashrate_hs"):
                        meta["hashrate_hs"] = st.get("hashrate_hs")
                        meta["hashrate_display"] = st.get("hashrate_display")
                except Exception:
                    pass
                comms.register_node(
                    node_type="dashboard",
                    capabilities=["dashboard", "mesh", "mining_engine", "comms"],
                    metadata=meta,
                )
                comms.heartbeat(metadata=meta)
            except Exception as e:
                logger.debug(f"mesh heartbeat: {e}")
            time.sleep(interval)

    threading.Thread(target=_loop, name="mesh-heartbeat", daemon=True).start()
    logger.info("mesh heartbeat + discovery started")
