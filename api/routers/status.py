from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_swarm_status():
    """Get high-level status of the swarm."""
    return {
        "status": "operational",
        "active_workers": 12,   # TODO: Pull from Redis / metrics
        "total_hashrate": 1240.5,
        "last_update": "2026-06-25T17:30:00Z"
    }
