import os
import json
import time
import logging
from typing import Optional, Dict, Any
from comms.layer import CommsLayer
from .policy_engine import PolicyEngine

try:
    from observability.metrics import get_metrics
    HAS_METRICS = True
except ImportError:
    HAS_METRICS = False

logger = logging.getLogger("aurora.sensing.integration")


class SensingIntegration:
    """
    Resilient bidirectional integration between aurora-swarm-btc and wifi-sensing-system.

    Now aligned with:
    - wifi-sensing-system/bridges/swarm_bridge.py (SwarmBridge + AuroraAdapter)
    - CommsLayer mesh participation (v1.1 contract)

    Sensing is a first-class citizen of the node grid.
    """

    def __init__(self, redis_url: Optional[str] = None, node_id: str = "sensing-main", stale_threshold: int = 30):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.node_id = node_id
        self.stale_threshold = stale_threshold

        # Use CommsLayer for mesh participation + resilience
        self.comms = CommsLayer(redis_url=self.redis_url, node_id=self.node_id)

        self.policy_engine = PolicyEngine()
        self.last_heartbeat = 0
        self.integration_healthy = False
        self.last_context_update = 0

        if HAS_METRICS:
            self.metrics = get_metrics()

        # Register as sensing node in the mesh
        self.comms.register_node(node_type="sensing", metadata={"role": "wifi-csi-provider"})
        logger.info("[MESH] SensingIntegration joined the Comms Layer mesh")

    def get_health_status(self) -> Dict[str, Any]:
        return {
            "healthy": self.integration_healthy,
            "last_heartbeat_age": time.time() - self.last_heartbeat if self.last_heartbeat else None,
            "last_context_age": time.time() - self.last_context_update if self.last_context_update else None,
            "threshold_seconds": self.stale_threshold,
            "node_id": self.node_id
        }

    def _report_health_metrics(self):
        if HAS_METRICS:
            status = self.get_health_status()
            # Assuming metrics module has this method
            pass

    def send_command_to_sensing(self, command: Dict[str, Any]):
        """Send command to wifi-sensing-system (via shared channel)."""
        self.comms.publish("swarm:commands", command)
        logger.info(f"[Swarm → Sensing] Command sent: {command.get('action', 'unknown')}")

    def publish_command(self, command: Dict[str, Any]):
        self.send_command_to_sensing(command)

    def check_heartbeat(self) -> bool:
        try:
            hb = self.comms.get_state("sensing:heartbeat")
            if hb:
                self.last_heartbeat = hb.get("timestamp", 0) if isinstance(hb, dict) else time.time()
                age = time.time() - self.last_heartbeat
                self.integration_healthy = age < self.stale_threshold
                self._report_health_metrics()
                return self.integration_healthy
        except Exception as e:
            logger.warning(f"Heartbeat check failed: {e}")
        self.integration_healthy = False
        self._report_health_metrics()
        return False

    def listen(self):
        """Main listening loop. Subscribes to sensing channels via mesh."""
        logger.info("[MESH] SensingIntegration listening on sensing channels...")

        # Subscribe to relevant patterns through CommsLayer if extended,
        # otherwise fall back to direct Redis for compatibility with SwarmBridge
        import redis
        r = redis.from_url(self.redis_url, decode_responses=True)
        pubsub = r.pubsub()
        pubsub.psubscribe("aurora:sensing:*")

        for message in pubsub.listen():
            if message['type'] == 'pmessage':
                try:
                    data = json.loads(message['data']) if isinstance(message['data'], str) else message['data']
                except Exception:
                    data = message['data']

                if isinstance(data, dict) and data.get("type") == "FULL_CONTEXT_UPDATE":
                    self.last_context_update = time.time()

                # Policy engine decides actions
                actions = self.policy_engine.evaluate(data if isinstance(data, dict) else {})
                for action in actions:
                    self.send_command_to_sensing(action)

                # Also publish important context via mesh for other components
                if isinstance(data, dict) and data.get("type") == "FULL_CONTEXT_UPDATE":
                    self.comms.publish_event("sensing_context_update", data)

            # Periodic health check
            if time.time() - last_check > 10:
                healthy = self.check_heartbeat()
                if not healthy:
                    logger.warning(f"[Sensing Health] DEGRADED: {self.get_health_status()}")
                last_check = time.time()


if __name__ == "__main__":
    integration = SensingIntegration()
    integration.listen()
