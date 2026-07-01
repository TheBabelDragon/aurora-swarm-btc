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
    - Swarm node registration & discovery (heartbeats, active nodes)
    - Convenience methods for common Aurora flows (events, commands, sensing, telemetry)
    - Event history for UI / replay
    - Basic resilience and logging

    This centralizes communication logic so workers, scheduler, sensing, and API
    can interact cleanly without duplicating Redis code.
    """

    EVENT_HISTORY_KEY = "events:history"
    MAX_EVENTS = 100

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
        """Publish a typed SwarmMessage and log to history if it's an event."""
        self.publish(channel, msg)
        if msg.type.startswith("event.") or msg.type == "event":
            self._log_event_to_history(msg)

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

    def _log_event_to_history(self, msg: SwarmMessage):
        """Store recent events for UI / debugging (capped list)."""
        try:
            event_data = msg.model_dump()
            self.r.lpush(f"aurora:{self.EVENT_HISTORY_KEY}", json.dumps(event_data))
            self.r.ltrim(f"aurora:{self.EVENT_HISTORY_KEY}", 0, self.MAX_EVENTS - 1)
        except Exception as e:
            logger.warning(f"Failed to log event to history: {e}")

    def get_recent_events(self, limit: int = 20) -> List[Dict]:
        """Retrieve recent events for UI and routers (newest first)."""
        try:
            raw_events = self.r.lrange(f"aurora:{self.EVENT_HISTORY_KEY}", 0, limit - 1) or []
            return [json.loads(e) for e in raw_events]
        except Exception:
            return []

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
        self.r.sadd(f"aurora:nodes:{node_type}", nid)
        self.r.expire(f"aurora:nodes:{node_type}", ttl * 2)
        logger.info(f"Registered node {nid} (type={node_type})")

    def heartbeat(self, node_id: Optional[str] = None):
        """Refresh heartbeat for a node."""
        nid = node_id or self.node_id
        self.register_node(nid)

    def get_active_nodes(self, node_type: Optional[str] = None) -> List[Dict]:
        """Discover currently active nodes (from registry)."""
        if node_type:
            node_ids = self.r.smembers(f"aurora:nodes:{node_type}") or []
        else:
            keys = self.r.keys("aurora:nodes:*")
            node_ids = [k.split(":")[-1] for k in keys if ":nodes:" in k and not k.endswith(":nodes:")]

        nodes = []
        for nid in node_ids:
            data = self.get_state(f"nodes:{nid}")
            if data:
                nodes.append(data)
        return nodes

    def get_workers(self) -> List[Dict]:
        """Convenience: get all active worker nodes."""
        return self.get_active_nodes(node_type="worker")

    # --- High-level Aurora-specific methods ---

    def publish_event(self, event_type: str, data: Dict[str, Any], source: Optional[str] = None):
        """Publish a swarm event and store in history."""
        msg = SwarmMessage(
            type=f"event.{event_type}",
            payload=data,
            source=source or self.node_id
        )
        self.publish_message("events", msg)
        # Legacy compatibility
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
            self.publish("swarm:commands", {"action": action, **(payload or {})})

    def send_sensing_command(self, action: str, **kwargs):
        """Convenience for commands targeting the sensing system."""
        self.send_command(action, payload=kwargs, target="sensing")

    # --- Subscription handling ---

    def subscribe(self, pattern: str, handler: Callable[[SwarmMessage], None]):
        """Register a handler for messages matching the pattern."""
        if pattern not in self.handlers:
            self.handlers[pattern] = []
        self.handlers[pattern].append(handler)
        logger.info(f"Subscribed handler to pattern: {pattern}")

    def start_listener(self, patterns: Optional[List[str]] = None):
        """Start listening loop for registered patterns. Blocking; run in thread."""
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

                    if isinstance(data, dict) and "type" in data:
                        try:
                            msg = SwarmMessage(**data)
                        except Exception:
                            msg = SwarmMessage(type="raw", payload={"raw": data})
                    else:
                        msg = SwarmMessage(type="raw", payload={"raw": data})

                    for pat, handlers in self.handlers.items():
                        if (pat.endswith("*") and msg.type.startswith(pat[:-1])) or pat == msg.type or pat in str(message.get("channel", "")):
                            for h in handlers:
                                try:
                                    h(msg)
                                except Exception as e:
                                    logger.error(f"Handler error for {pat}: {e}")
                except Exception as e:
                    logger.error(f"Listener error: {e}")

    def close(self):
        try:
            self.pubsub.close()
        except:
            pass
        logger.info("CommsLayer closed")


if __name__ == "__main__":
    layer = CommsLayer(node_id="test-node")
    layer.register_node(node_type="worker")

    def on_event(msg: SwarmMessage):
        print(f"[Handler] Event received: {msg.type} from {msg.source}")

    layer.subscribe("event.*", on_event)
    print("CommsLayer example ready. Workers:", layer.get_workers())
    print("Recent events:", layer.get_recent_events(5))
