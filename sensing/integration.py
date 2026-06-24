import os
import json
import redis
from typing import Callable, Optional

class SensingIntegration:
    """Bidirectional integration between WiFi CSI sensing and aurora-swarm-btc."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.r = redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.r.pubsub()

    def publish_command(self, command: dict):
        """Send a command back to the sensing system or other components."""
        self.r.publish("aurora:swarm:commands", json.dumps(command))
        print(f"[Swarm] Published command: {command}")

    def listen(self, callback: Optional[Callable] = None):
        self.pubsub.psubscribe("aurora:sensing:*")
        print("[SensingIntegration] Listening on aurora:sensing:* channels...")

        for message in self.pubsub.listen():
            if message['type'] == 'pmessage':
                channel = message['channel']
                try:
                    data = json.loads(message['data'])
                except:
                    data = message['data']

                print(f"[Sensing] {channel} → {data}")

                if callback:
                    callback(channel, data)
                else:
                    self._default_reaction(channel, data)

    def _default_reaction(self, channel: str, data):
        if isinstance(data, dict):
            event_type = data.get("type", "")
            if event_type == "OCCUPANCY_DETECTED":
                count = data.get("count", 0)
                if count > 2:
                    print("[Swarm Policy] Multiple humans detected → Suggesting power reduction")
                    self.publish_command({"action": "scale_down", "reason": "occupancy", "factor": 0.7})
            elif "ANOMALY" in event_type:
                print("[Swarm Policy] Anomaly detected → Security alert mode")
                self.publish_command({"action": "security_mode", "reason": "physical_anomaly"})

if __name__ == "__main__":
    integration = SensingIntegration()
    integration.listen()