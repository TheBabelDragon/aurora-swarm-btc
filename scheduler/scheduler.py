import time
import logging
from comms.layer import CommsLayer

"""
Aurora Swarm BTC Scheduler (Autonomous Mesh Coordinator)

The scheduler now provides real practical control over the swarm:
- Discovers and monitors all workers
- Reacts to aggregate state and sensing context
- Issues useful fleet-wide commands (intensity scaling, pause, restart)
"""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aurora-scheduler-mesh")

comms = CommsLayer(node_id="scheduler")


def get_aggregate_state():
    """Collect useful state from the mesh."""
    workers = comms.get_workers()
    total_hashrate = 0.0
    unhealthy = 0

    for w in workers:
        meta = w.get("metadata", {})
        hashrate = meta.get("hashrate_ghs", 0) or 0
        total_hashrate += hashrate
        if meta.get("status") not in ["mining", None]:
            unhealthy += 1

    sensing_health = comms.get_state("sensing:heartbeat", {})
    sensing_healthy = sensing_health.get("healthy", True) if isinstance(sensing_health, dict) else True

    return {
        "worker_count": len(workers),
        "total_hashrate_ghs": round(total_hashrate, 1),
        "unhealthy_workers": unhealthy,
        "sensing_healthy": sensing_healthy
    }


def main():
    logger.info("[MESH] Autonomous Scheduler started - joining comms mesh...")

    comms.register_node(node_type="scheduler", metadata={"role": "autonomous_coordinator"})

    last_action = 0

    while True:
        now = time.time()
        state = get_aggregate_state()

        logger.info(f"[STATE] Workers: {state['worker_count']} | Hashrate: {state['total_hashrate_ghs']} GH/s | Unhealthy: {state['unhealthy_workers']} | Sensing OK: {state['sensing_healthy']}")

        # === Practical autonomous control logic ===

        # 1. If too many workers unhealthy, try to recover them
        if state["unhealthy_workers"] > max(1, state["worker_count"] // 3) and now - last_action > 60:
            logger.warning("[CONTROL] Many unhealthy workers - broadcasting restart")
            comms.broadcast_to_workers({"action": "restart_miner", "reason": "scheduler_recovery"})
            last_action = now

        # 2. React to sensing (if available) - reduce power when high occupancy
        sensing_ctx = comms.get_state("sensing:latest_context", {})
        if isinstance(sensing_ctx, dict):
            tracks = sensing_ctx.get("tracks", [])
            if len(tracks) > 4 and now - last_action > 45:  # High physical presence
                logger.info("[CONTROL] High occupancy detected - scaling down fleet intensity")
                comms.broadcast_to_workers({
                    "action": "adjust_intensity",
                    "factor": 0.85,
                    "reason": "high_physical_occupancy"
                })
                last_action = now

        # 3. Gentle hashrate targeting / power management example
        if state["total_hashrate_ghs"] > 500 and now - last_action > 120:
            logger.info("[CONTROL] High total hashrate - gentle scale down for thermals")
            comms.broadcast_to_workers({
                    "action": "adjust_intensity",
                    "factor": 0.92,
                    "reason": "thermal_management"
                })
            last_action = now

        comms.heartbeat(metadata=state)
        time.sleep(20)


if __name__ == "__main__":
    main()
