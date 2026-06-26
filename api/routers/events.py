from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_recent_events(limit: int = 20):
    """Get recent events and decisions from the swarm."""
    return {
        "events": [
            {"timestamp": "2026-06-25T17:20:00Z", "type": "scale_down", "reason": "high_occupancy"},
            {"timestamp": "2026-06-25T17:15:00Z", "type": "security_mode", "reason": "anomaly_detected"},
            {"timestamp": "2026-06-25T17:10:00Z", "type": "scale_up", "reason": "low_occupancy"}
        ][:limit]
    }
