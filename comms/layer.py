import os
import json
import time
import logging
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

import redis

logger = logging.getLogger("aurora.comms")


class SwarmMessage(BaseModel):
    """Base message model for structured swarm communication."""
    type: str = Field(..., description="Message type e.g. event, command, telemetry, context")
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
    source: Optional[str] = Field(None, description="Source node or component ID")
    target: Optional[str] = Field(None, description="Optional specific target node")
    correlation_id: Optional[str] = None


class CommsLayer:
    """
    High-level Communications Layer for the Aurora Swarm.

    Builds on Redis pub/sub + key-value store to provide:
    - Structured message publishing
    - Topic/pattern subscription with handlers
    - Swarm node registration & discovery (with heartbeats)
    - Convenience methods for common Aurora flows (events, commands, sensing, telemetry)
    - Basic resilience and logging

    This centralizes communication logic so workers, scheduler, sensing, and API
    can interact cleanly without duplicating Redis code.
    """

    def __init__(self, redis_url: Optional[str] = None, node_id: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.node_id = node_id or os.getenv("AURORA_NODE_ID", "unknown-node")
        self.r = redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.r.pubsub()
        self.handlers: Dict[str, List[Callable[[SwarmMessage], None]]] = {}
        self._subscribed_patterns: List[str] = []
        logger.info(f"CommsLayer initialized for node={self.node_id} redis={self.redis_url}")

    # --- Low-level primitives ---

    def publish(self, channel: str, message: Any):
        """Publish raw or structured message to a channel."""
        if isinstance(message, (dict, list)):
            message = json.dumps(message)
        elif isinstance(message, BaseModel):
            message = message.model_dump_json()
        prefixed = f"aurora:{channel}"
        self.r.publish(prefixed, message)
        logger.debug(f"Published to {prefixed}")

    def publish_message(self, channel: str, msg: SwarmMessage):
        """Publish a typed SwarmMessage."""
        self.publish(channel, msg)

    def set_state(self, key: str, value: Any, expire: int = 0):
        """Set shared state (prefixed)."""
        full_key = f"aurora:{key}"
        val = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        self.r.set(full_key, val)
        if expire > 0:
            self.r.expire(full_key, expire)

    def get_state(self, key: str, default: Any = None) -> Any:
        val = self.r.get(f"aurora:{key}")
        if val is None:
            return default
        try:
            return json.loads(val)
        except Exception:
            return val

    # --- Node Registry (for swarm discovery) ---

    def register_node(self, node_id: Optional[str] = None, node_type: str = "worker", metadata: Optional[Dict] = None, ttl: int = 60):
        """Register this node in the swarm registry with TTL heartbeat."""
        nid = node_id or self.node_id
        data = {
            "node_id": nid,
            "type": node_type,
            "last_seen": time.time(),
            "metadata": metadata or {}
        }
        self.set_state(f"nodes:{nid}", data, expire=ttl)
        # Also add to type set for easy discovery
        self.r.sadd(f"aurora:nodes:{node_type}", nid)
        self.r.expire(f"aurora:nodes:{node_type}", ttl * 2)
        logger.info(f"Registered node {nid} (type={node_type})")

    def heartbeat(self, node_id: Optional[str] = None):
        """Refresh heartbeat for a node."""
        nid = node_id or self.node_id
        self.register_node(nid)  # re-sets with fresh TTL

    def get_active_nodes(self, node_type: Optional[str] = None) -> List[Dict]:
        """Discover currently active nodes."""
        if node_type:
            node_ids = self.r.smembers(f"aurora:nodes:{node_type}") or []
        else:
            # Fallback: scan keys (simplified)
            keys = self.r.keys("aurora:nodes:*")
            node_ids = [k.split(":")[-1] for k in keys if k.startswith("aurora:nodes:")]

        nodes = []
        for nid in node_ids:
            data = self.get_state(f"nodes:{nid}")
            if data:
                nodes.append(data)
        return nodes

    # --- High-level Aurora-specific methods ---

    def publish_event(self, event_type: str, data: Dict[str, Any], source: Optional[str] = None):
        """Publish a swarm event (e.g. worker_joined, mining_started, context_updated)."""
        msg = SwarmMessage(
            type=f"event.{event_type}",
            payload=data,
            source=source or self.node_id
        )
        self.publish_message("events", msg)
        # Also broadcast via legacy channel for compatibility
        self.publish("events", {"type": event_type, "data": data, "source": source or self.node_id})

    def publish_telemetry(self, metrics: Dict[str, Any], source: Optional[str] = None):
        """Publish telemetry / metrics from a worker or component."""
        msg = SwarmMessage(
            type="telemetry",
            payload=metrics,
            source=source or self.node_id
        )
        self.publish_message("telemetry", msg)

    def send_command(self, action: str, payload: Dict[str, Any] = None, target: Optional[str] = None):
        """Send a command (to sensing, to workers, or specific target)."""
        cmd = SwarmMessage(
            type="command",
            payload={"action": action, **(payload or {})},
            source=self.node_id,
            target=target
        )
        if target:
            self.publish_message(f"commands:{target}", cmd)
        else:
            self.publish_message("commands", cmd)
            # Legacy compatibility
            self.publish("swarm:commands", {"action": action, **(payload or {})})

    def send_sensing_command(self, action: str, **kwargs):
        """Convenience for commands targeting the sensing system."""
        self.send_command(action, payload=kwargs, target="sensing")

    # --- Subscription handling ---

    def subscribe(self, pattern: str, handler: Callable[[SwarmMessage], None]):
        """Register a handler for messages matching the pattern (e.g. 'events.*' or 'sensing:*').
        Note: Actual listening loop must be started separately (see start_listener)."""
        if pattern not in self.handlers:
            self.handlers[pattern] = []
        self.handlers[pattern].append(handler)
        logger.info(f"Subscribed handler to pattern: {pattern}")

    def start_listener(self, patterns: Optional[List[str]] = None):
        """Start listening loop for registered patterns. Runs blocking; use in thread or dedicated process."""
        patterns = patterns or list(self.handlers.keys()) or ["aurora:events", "aurora:commands", "aurora:sensing:*"]
        for p in patterns:
            if p not in self._subscribed_patterns:
                self.pubsub.psubscribe(p)
                self._subscribed_patterns.append(p)

        logger.info(f"CommsLayer listener started on patterns: {self._subscribed_patterns}")

        for message in self.pubsub.listen():
            if message["type"] in ("pmessage", "message"):
                try:
                    raw = message.get("data", "")
                    if isinstance(raw, str):
                        try:
                            data = json.loads(raw)
                        except:
                            data = raw
                    else:
                        data = raw

                    # Try to parse as SwarmMessage
                    if isinstance(data, dict) and "type" in data:
                        try:
                            msg = SwarmMessage(**data)
                        except Exception:
                            msg = SwarmMessage(type="raw", payload={"raw": data})
                    else:
                        msg = SwarmMessage(type="raw", payload={"raw": data})

                    # Dispatch to matching handlers
                    for pat, handlers in self.handlers.items():
                        # Simple pattern match (extend with fnmatch if needed)
                        if pat.endswith("*") and msg.type.startswith(pat[:-1]):
                            for h in handlers:
                                try:
                                    h(msg)
                                except Exception as e:
                                    logger.error(f"Handler error for {pat}: {e}")
                        elif pat == msg.type or pat in message.get("channel", ""):
                            for h in handlers:
                                try:
                                    h(msg)
                                except Exception as e:
                                    logger.error(f"Handler error: {e}")
                except Exception as e:
                    logger.error(f"Listener error: {e}")

    def close(self):
        try:
            self.pubsub.close()
        except:
            pass
        logger.info("CommsLayer closed")


# Example usage (for reference / testing)
if __name__ == "__main__":
    layer = CommsLayer(node_id="test-node")
    layer.register_node(node_type="worker")

    def on_event(msg: SwarmMessage):
        print(f"[Handler] Event received: {msg.type} from {msg.source}")

    layer.subscribe("event.*", on_event)
    # In real use: threading.Thread(target=layer.start_listener).start()
    print("CommsLayer example ready. Active nodes:", layer.get_active_nodes())
