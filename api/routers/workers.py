from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def list_workers():
    """List all active workers in the swarm."""
    return {
        "workers": [
            {"id": "worker-01", "status": "mining", "hashrate": 104.2, "temp_c": 67},
            {"id": "worker-02", "status": "mining", "hashrate": 98.7, "temp_c": 71},
            {"id": "worker-03", "status": "idle", "hashrate": 0.0, "temp_c": 52}
        ]
    }
