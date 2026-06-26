from fastapi import APIRouter, Depends
import redis

from ..dependencies import get_redis

router = APIRouter()

@router.get("/")
async def get_metrics_summary(r: redis.Redis = Depends(get_redis)):
    """Get summarized metrics (pulls live data from Redis when available)."""
    try:
        hashrate = float(r.get("worker:hashrate") or 0)
        shares = int(r.get("cluster:shares_accepted") or 0)
    except:
        hashrate = 0.0
        shares = 0

    return {
        "total_hashrate_ghs": hashrate,
        "accepted_shares": shares,
        "active_workers": 12,
        "avg_temp_c": 68.5
    }
