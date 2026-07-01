from fastapi import APIRouter, Depends
import redis

from ..dependencies import get_redis
from comms.layer import CommsLayer

router = APIRouter()

comms = CommsLayer(node_id="api-metrics")

@router.get("/")
async def get_metrics_summary(r: redis.Redis = Depends(get_redis)):
    """Get summarized metrics (dynamic where possible via Redis + CommsLayer)."""
    try:
        hashrate = float(r.get("worker:hashrate") or 0)
        shares = int(r.get("cluster:shares_accepted") or 0)
    except:
        hashrate = 0.0
        shares = 0

    workers = comms.get_workers()
    active_workers = len(workers) if workers else 12  # fallback

    return {
        "total_hashrate_ghs": hashrate,
        "accepted_shares": shares,
        "active_workers": active_workers,
        "avg_temp_c": 68.5,  # TODO: aggregate from worker telemetry
        "source": "comms-layer + redis"
    }