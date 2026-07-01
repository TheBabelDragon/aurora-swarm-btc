from fastapi import APIRouter
from comms.layer import CommsLayer

router = APIRouter()

comms = CommsLayer(node_id="api-workers")

@router.get("/")
async def list_workers():
    """List all active workers from the CommsLayer node registry (dynamic)."""
    workers = comms.get_workers()
    if not workers:
        # Fallback demo data until nodes register themselves
        workers = [
            {"node_id": "worker-01", "type": "worker", "last_seen": "2026-06-30T21:00:00Z", "metadata": {"status": "mining", "hashrate": 104.2, "temp_c": 67}},
            {"node_id": "worker-02", "type": "worker", "last_seen": "2026-06-30T21:00:00Z", "metadata": {"status": "mining", "hashrate": 98.7, "temp_c": 71}},
            {"node_id": "worker-03", "type": "worker", "last_seen": "2026-06-30T20:55:00Z", "metadata": {"status": "idle", "hashrate": 0.0, "temp_c": 52}}
        ]
    return {"workers": workers, "source": "comms-layer-node-registry"}