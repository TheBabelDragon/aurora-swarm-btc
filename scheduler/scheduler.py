import time
import logging
from comms.layer import CommsLayer

"""
Aurora Swarm BTC Scheduler (Mesh-enabled)

The scheduler is now a full citizen of the Comms Layer mesh.
It discovers live workers, monitors aggregate state, and issues commands.
"""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aurora-scheduler-mesh")

comms = CommsLayer(node_id="scheduler")


def main():
    logger.info("[MESH] Scheduler started - joining comms mesh...")

    # Join the mesh
    comms.register_node(node_type="scheduler", metadata={"role": "coordinator"})

    last_discovery = 0

    while True:
        now = time.time()

        # Discover live workers in the mesh
        if now - last_discovery > 30:
            workers = comms.get_workers()
            logger.info(f"[MESH] Discovered {len(workers)} active workers")
            for w in workers:
                logger.info(f"  - {w.get('node_id')} (last seen: {w.get('last_seen')})")
            last_discovery = now

        # Simple entropy-based coordination (placeholder for real policy)
        entropy = comms.get_state("entropy", 1.0)
        if entropy > 3.0:
            # Example: broadcast a gentle scale command via mesh
            comms.broadcast_to_workers({
                "action": "adjust_intensity",
                "factor": 0.95,
                "reason": "high_entropy"
            })
            logger.info("[MESH] Broadcasted intensity reduction (high entropy)")

        # Heartbeat so scheduler stays visible in the mesh
        comms.heartbeat()

        time.sleep(15)


if __name__ == "__main__":
    main()
