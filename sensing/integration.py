import os
import json
import redis
import time
from typing import Optional
from .policy_engine import PolicyEngine

try:
    from observability.metrics import get_metrics
    HAS_METRICS = True
except ImportError:
    HAS_METRICS = False

class SensingIntegration:
    """Resilient + bidirectional integration with health reporting."""

    def __init__(self, redis_url: Optional[str] = None, stale_threshold: int = 30):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.r = redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.r.pubsub()
        self.policy_engine = PolicyEngine()
        self.stale_threshold = stale_threshold
        self.last_heartbeat = 0
        self.integration_healthy = False
        self.last_context_update = 0

        if HAS_METRICS:
            self.metrics = get_metrics()

    def get_health_status(self):
        return {
            "healthy": self.integration_healthy,
            "last_heartbeat_age": time.time() - self.last_heartbeat if self.last_heartbeat else None,
            "last_context_age": time.time() - self.last_context_update if self.last_context_update else None,
            "threshold_seconds": self.stale_threshold
        }

    def _report_health_metrics(self):
        if HAS_METRICS:
            status = self.get_health_status()
            self.metrics.update_integration_health(
                healthy=status["healthy"],
                heartbeat_age=status.get("last_heartbeat_age"),
                context_age=status.get("last_context_age")
            )

    def send_command_to_sensing(self, command: dict):
        self.r.publish("aurora:swarm:commands", json.dumps(command))
        print(f"[Swarm → Sensing] Sent command: {command}")

    def publish_command(self, command):
        self.send_command_to_sensing(command)

    def check_heartbeat(self):
        try:
            hb = self.r.get("aurora:sensing:heartbeat")
            if hb:
                data = json.loads(hb)
                self.last_heartbeat = data.get("timestamp", 0)
                age = time.time() - self.last_heartbeat
                self.integration_healthy = age < self.stale_threshold
                self._report_health_metrics()
                return self.integration_healthy
        except Exception:
            pass
        self.integration_healthy = False
        self._report_health_metrics()
        return False

    def listen(self):
        self.pubsub.psubscribe("aurora:sensing:*")
        print("[SensingIntegration] Listening with health metrics...")

        last_check = time.time()

        for message in self.pubsub.listen():
            if message['type'] == 'pmessage':
                try:
                    data = json.loads(message['data'])
                except:
                    data = message['data']

                if data.get("type") == "FULL_CONTEXT_UPDATE":
                    self.last_context_update = time.time()

                actions = self.policy_engine.evaluate(data)
                for action in actions:
                    self.send_command_to_sensing(action)

            if time.time() - last_check > 10:
                healthy = self.check_heartbeat()
                if not healthy:
                    print(f"[Integration Health] DEGRADED: {self.get_health_status()}")
                last_check = time.time()

if __name__ == "__main__":
    integration = SensingIntegration()
    integration.listen()