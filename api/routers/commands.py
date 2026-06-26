from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class Command(BaseModel):
    action: str
    params: dict = {}

@router.post("/")
async def send_command(command: Command):
    """Send a command to the swarm (e.g. scale, security_mode)."""
    # TODO: Publish to Redis bus (aurora:swarm:commands)
    return {
        "status": "command_received",
        "action": command.action,
        "params": command.params
    }
