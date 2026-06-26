from fastapi import APIRouter, Depends
import redis

from ..dependencies import get_redis

router = APIRouter()

@router.get("/")
async def get_swarm_status(r: redis.Redis = Depends(get_redis)):
    """Get current swarm status (pulls from Redis where possible)."""
    try:
        hashrate = r.get("worker:hashrate") or 0
        status = r.get("worker:status") or "unknown"
    except:
        hashrate = 0
        status = "unknown"

    return {
        "status": "operational",
        "active_workers": 12,
        "total_hashrate_ghs": float(hashrate) if hashrate else 0.0,
        "overall_status": status
    }
