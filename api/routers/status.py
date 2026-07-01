from fastapi import APIRouter, Depends
import redis

from ..dependencies import get_redis
from comms.layer import CommsLayer

router = APIRouter()

comms = CommsLayer(node_id="api-status")

@router.get("/")
async def get_swarm_status(r: redis.Redis = Depends(get_redis)):
    """Get current swarm status (dynamic via Redis + CommsLayer node registry)."""
    try:
        hashrate = r.get("worker:hashrate") or 0
        status_val = r.get("worker:status") or "operational"
    except:
        hashrate = 0
        status_val = "operational"

    workers = comms.get_workers()
    active_workers = len(workers) if workers else 12

    return {
        "status": "operational",
        "active_workers": active_workers,
        "total_hashrate_ghs": float(hashrate) if hashrate else 0.0,
        "overall_status": status_val,
        "source": "comms-layer"
    }