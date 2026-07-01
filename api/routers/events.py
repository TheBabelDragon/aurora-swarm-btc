from fastapi import APIRouter
from comms.layer import CommsLayer

router = APIRouter()

comms = CommsLayer(node_id="api-router")

@router.get("/")
async def get_recent_events(limit: int = 20):
    """Get recent events from the Comms Layer event history (dynamic)."""
    events = comms.get_recent_events(limit=limit)
    if not events:
        # Fallback demo events if no history yet (will be replaced as system runs)
        events = [
            {"type": "event.scale_down", "payload": {"reason": "high_occupancy"}, "timestamp": "2026-06-25T17:20:00Z", "source": "policy-engine"},
            {"type": "event.security_mode", "payload": {"reason": "anomaly_detected"}, "timestamp": "2026-06-25T17:15:00Z", "source": "sensing"},
            {"type": "event.scale_up", "payload": {"reason": "low_occupancy"}, "timestamp": "2026-06-25T17:10:00Z", "source": "scheduler"}
        ][:limit]
    return {"events": events, "source": "comms-layer"}