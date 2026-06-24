import os
import json
import redis
from typing import Optional, Callable, Dict, Any

class SensingIntegration:
    """Fully working integration that consumes rich sensing data and can trigger real actions."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.r = redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.r.pubsub()

    def publish_command(self, command: Dict[str, Any]):
        """Publish a command that the swarm/scheduler can act on."""
        self.r.publish("aurora:swarm:commands", json.dumps(command))
        print(f"[Swarm → Action] Published command: {command}")

    def listen(self, callback: Optional[Callable] = None):
        self.pubsub.psubscribe("aurora:sensing:*")
        print("[SensingIntegration] Listening and ready to act on rich context...")

        for message in self.pubsub.listen():
            if message['type'] == 'pmessage':
                channel = message['channel']
                try:
                    data = json.loads(message['data'])
                except:
                    data = message['data']

                if callback:
                    callback(channel, data)
                else:
                    self._react(channel, data)

    def _react(self, channel: str, data: Dict[str, Any]):
        if not isinstance(data, dict):
            return

        data_type = data.get("type", "")

        if data_type == "FULL_CONTEXT_UPDATE":
            tracks = data.get("tracks", [])
            events = data.get("events", [])
            memory = data.get("memory_summary", {})

            print(f"[Sensing] Full context received → {len(tracks)} tracks")

            # Working reactions
            if any("ANOMALY" in str(e) for e in events):
                cmd = {"action": "security_mode", "reason": "physical_anomaly", "source": "sensing"}
                self.publish_command(cmd)

            elif len(tracks) >= 3:
                cmd = {
                    "action": "scale_down",
                    "factor": 0.6,
                    "reason": "high_occupancy",
                    "source": "sensing"
                }
                self.publish_command(cmd)

            elif len(tracks) == 0:
                cmd = {"action": "scale_up", "factor": 1.15, "reason": "empty_hall", "source": "sensing"}
                self.publish_command(cmd)

        elif data_type == "OCCUPANCY_DETECTED":
            count = data.get("count", 0)
            if count > 2:
                self.publish_command({"action": "scale_down", "factor": 0.7, "reason": "occupancy"})

if __name__ == "__main__":
    integration = SensingIntegration()
    integration.listen()