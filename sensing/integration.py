import os
import json
import redis
from typing import Optional
from .policy_engine import PolicyEngine

class SensingIntegration:
    """Fully working integration using the PolicyEngine."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.r = redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.r.pubsub()
        self.policy_engine = PolicyEngine()

    def publish_command(self, command):
        self.r.publish("aurora:swarm:commands", json.dumps(command))
        print(f"[Swarm Action] {command}")

    def listen(self):
        self.pubsub.psubscribe("aurora:sensing:*")
        print("[SensingIntegration] Listening with PolicyEngine...")

        for message in self.pubsub.listen():
            if message['type'] == 'pmessage':
                try:
                    data = json.loads(message['data'])
                except:
                    data = message['data']

                actions = self.policy_engine.evaluate(data)
                for action in actions:
                    self.publish_command(action)

if __name__ == "__main__":
    integration = SensingIntegration()
    integration.listen()