import os
import json
import redis
import time
from typing import Optional
from .policy_engine import PolicyEngine

class SensingIntegration:
    """Resilient integration with heartbeat monitoring and graceful degradation."""

    def __init__(self, redis_url: Optional[str] = None, stale_threshold: int = 30):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.r = redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.r.pubsub()
        self.policy_engine = PolicyEngine()
        self.stale_threshold = stale_threshold  # seconds
        self.last_heartbeat = 0
        self.integration_healthy = False

    def publish_command(self, command):
        self.r.publish("aurora:swarm:commands", json.dumps(command))
        print(f"[Swarm Action] {command}")

    def check_heartbeat(self):
        """Check if sensing system is still sending heartbeats."""
        try:
            hb = self.r.get("aurora:sensing:heartbeat")
            if hb:
                data = json.loads(hb)
                self.last_heartbeat = data.get("timestamp", 0)
                age = time.time() - self.last_heartbeat
                self.integration_healthy = age < self.stale_threshold
                return self.integration_healthy
        except Exception:
            pass
        self.integration_healthy = False
        return False

    def listen(self):
        self.pubsub.psubscribe("aurora:sensing:*")
        print("[SensingIntegration] Listening with resilience...")

        last_check = time.time()

        for message in self.pubsub.listen():
            if message['type'] == 'pmessage':
                try:
                    data = json.loads(message['data'])
                except:
                    data = message['data']

                # Process normal sensing data
                actions = self.policy_engine.evaluate(data)
                for action in actions:
                    self.publish_command(action)

            # Periodic heartbeat check
            if time.time() - last_check > 10:
                healthy = self.check_heartbeat()
                if not healthy:
                    print("[Warning] Sensing heartbeat stale or missing - running in degraded mode")
                last_check = time.time()

if __name__ == "__main__":
    integration = SensingIntegration()
    integration.listen()