from fastapi import APIRouter, Depends
from pydantic import BaseModel
import json
import redis

from ..dependencies import get_redis

from ..main import broadcast_event

router = APIRouter()

class Command(BaseModel):
    action: str
    params: dict = {}
    reason: str = None

@router.post("/")
async def send_command(command: Command, r: redis.Redis = Depends(get_redis)):
    payload = {
        "action": command.action,
        "params": command.params,
        "reason": command.reason
    }
    r.publish("aurora:swarm:commands", json.dumps(payload))

    # Also broadcast via WebSocket so connected clients see it
    await broadcast_event({"type": "command_sent", "data": payload})

    return {"status": "command_sent", "action": command.action}
