from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_metrics_summary():
    """Get summarized metrics from the swarm."""
    return {
        "total_hashrate_ghs": 1240.5,
        "accepted_shares_24h": 184320,
        "active_workers": 12,
        "avg_temperature_c": 68.4
    }
