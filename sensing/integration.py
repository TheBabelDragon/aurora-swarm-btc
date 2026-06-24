import os
import json
import redis
from typing import Callable

class SensingIntegration:
    """Listens for events from the WiFi CSI sensing system and reacts."""

    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.r = redis.from_url(self.redis_url)
        self.pubsub = self.r.pubsub()

    def listen(self, callback: Callable = None):
        self.pubsub.psubscribe("aurora:sensing:*")
        print("[SensingIntegration] Listening for CSI events on aurora:sensing:*")

        for message in self.pubsub.listen():
            if message['type'] == 'pmessage':
                channel = message['channel'].decode()
                try:
                    data = json.loads(message['data'].decode())
                except:
                    data = message['data'].decode()

                print(f"[Sensing] Received on {channel}: {data}")

                if callback:
                    callback(channel, data)
                else:
                    self.default_handler(channel, data)

    def default_handler(self, channel: str, data):
        if "OCCUPANCY_DETECTED" in str(data) or "ANOMALY" in str(data):
            print("[Swarm] → Physical context change detected. Considering power adjustment...")
            # Example: could call into scheduler here

if __name__ == "__main__":
    integration = SensingIntegration()
    integration.listen()