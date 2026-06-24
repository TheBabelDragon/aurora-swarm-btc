import os
import json
import redis
from typing import Callable, Optional, Dict, Any

class SensingIntegration:
    """Secure, rich data integration between WiFi CSI sensing and aurora-swarm-btc."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.r = redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.r.pubsub()

    def publish_command(self, command: Dict[str, Any]):
        """Send commands back to sensing or other systems."""
        self.r.publish("aurora:swarm:commands", json.dumps(command))

    def listen(self, callback: Optional[Callable] = None):
        self.pubsub.psubscribe("aurora:sensing:*")
        print("[SensingIntegration] Listening for rich context on aurora:sensing:* ...")

        for message in self.pubsub.listen():
            if message['type'] == 'pmessage':
                channel = message['channel']
                try:
                    data = json.loads(message['data'])
                except:
                    data = message['data']

                print(f"[Sensing] {channel}")

                if callback:
                    callback(channel, data)
                else:
                    self._process_rich_data(channel, data)

    def _process_rich_data(self, channel: str, data: Dict[str, Any]):
        if not isinstance(data, dict):
            return

        data_type = data.get("type", "")

        if data_type == "FULL_CONTEXT_UPDATE":
            tracks = data.get("tracks", [])
            events = data.get("events", [])
            print(f"  → Received full context: {len(tracks)} tracks, events={events}")

            # Example smart reactions
            if any("ANOMALY" in str(e) for e in events):
                print("  → ANOMALY detected → Triggering security policy")
                self.publish_command({"action": "security_mode", "source": "sensing"})

            if len(tracks) > 3:
                print("  → High occupancy → Suggesting power scaling")
                self.publish_command({"action": "scale_down", "factor": 0.65, "source": "sensing"})

        elif data_type == "OCCUPANCY_DETECTED":
            count = data.get("count", 0)
            print(f"  → Occupancy update: {count} people")

if __name__ == "__main__":
    integration = SensingIntegration()
    integration.listen()