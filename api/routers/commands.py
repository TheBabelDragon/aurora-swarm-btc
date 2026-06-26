from fastapi import APIRouter, Depends
from pydantic import BaseModel
import json
import redis
import os

from ..dependencies import get_redis

router = APIRouter()

class Command(BaseModel):
    action: str
    params: dict = {}
    reason: str = None

@router.post("/")
async def send_command(command: Command, r: redis.Redis = Depends(get_redis)):
    """Send a command to the swarm. This publishes to the Redis bus."""
    payload = {
        "action": command.action,
        "params": command.params,
        "reason": command.reason
    }
    r.publish("aurora:swarm:commands", json.dumps(payload))
    return {
        "status": "command_sent",
        "action": command.action,
        "params": command.params
    }
