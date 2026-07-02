import os
import json
import time
import logging
from typing import Any, Callable, Dict, List, Optional, Set
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
    High-level Communications Layer for the Aurora Swarm (Hybrid Node Model).

    Supports:
    - Core node types (worker, coordinator, sensing, interface, gateway)
    - Explicit capabilities for fine-grained behavior
    - Mesh participation with registration + heartbeats
    - Targeted messaging and broadcasting
    - Event history
    """

    EVENT_HISTORY_KEY = "events:history"
    MAX_EVENTS = 100

    CORE_NODE_TYPES = {"worker", "coordinator", "sensing", "interface", "gateway"}

    def __init__(self, redis_url: Optional[str] = None, node_id: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis:6379/0")
        self.node_id = node_id or os.getenv("AURORA_NODE_ID", "unknown-node")
        self.r = redis.from_url(self.redis_url, decode_responses=True)
        self.pubsub = self.r.pubsub()
        self.handlers: Dict[str, List[Callable[[SwarmMessage], None]]] = {}
        self._subscribed_patterns: List[str] = []
        logger.info(f"CommsLayer initialized for node={self.node_id}")

    # --- Core primitives ---

    def publish(self, channel: str, message: Any):
        if isinstance(message, (dict, list)):
            message = json.dumps(message)
        elif isinstance(message, BaseModel):
            message = message.model_dump_json()
        prefixed = f"aurora:{channel}"
        self.r.publish(prefixed, message)

    def publish_message(self, channel: str, msg: SwarmMessage):
        self.publish(channel, msg)
        if msg.type.startswith("event.") or msg.type == "event":
            self._log_event_to_history(msg)

    def set_state(self, key: str, value: Any, expire: int = 0):
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
        try:
            event_data = msg.model_dump()
            self.r.lpush(f"aurora:{self.EVENT_HISTORY_KEY}", json.dumps(event_data))
            self.r.ltrim(f"aurora:{self.EVENT_HISTORY_KEY}", 0, self.MAX_EVENTS - 1)
        except Exception as e:
            logger.warning(f"Failed to log event to history: {e}")

    def get_recent_events(self, limit: int = 20) -> List[Dict]:
        try:
            raw_events = self.r.lrange(f"aurora:{self.EVENT_HISTORY_KEY}", 0, limit - 1) or []
            return [json.loads(e) for e in raw_events]
        except Exception:
            return []

    # --- Mesh / Node Registration with Capabilities ---

    def register_node(
        self,
        node_id: Optional[str] = None,
        node_type: str = "worker",
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        ttl: int = 90
    ):
        """
        Register this node in the mesh with type and capabilities.

        node_type should be one of: worker, coordinator, sensing, interface, gateway
        capabilities: list of things this node can do (e.g. ["gpu_mining", "intensity_control"])
        """
        if node_type not in self.CORE_NODE_TYPES:
            logger.warning(f"Unknown node_type '{node_type}'. Consider using one of {self.CORE_NODE_TYPES}")

        nid = node_id or self.node_id
        caps: Set[str] = set(capabilities or [])

        data = {
            "node_id": nid,
            "type": node_type,
            "capabilities": list(caps),
            "last_seen": time.time(),
            "metadata": metadata or {}
        }

        self.set_state(f"nodes:{nid}", data, expire=ttl)
        self.r.sadd(f"aurora:nodes:{node_type}", nid)
        self.r.expire(f"aurora:nodes:{node_type}", ttl * 2)

        # Also index by capability for fast lookup
        for cap in caps:
            self.r.sadd(f"aurora:capability:{cap}", nid)

        logger.info(f"[MESH] Registered {nid} (type={node_type}, capabilities={caps})")

    def heartbeat(self, node_id: Optional[str] = None, metadata: Optional[Dict] = None):
        nid = node_id or self.node_id
        existing = self.get_state(f"nodes:{nid}")
        if existing:
            existing["last_seen"] = time.time()
            if metadata:
                existing["metadata"].update(metadata)
            self.set_state(f"nodes:{nid}", existing, expire=90)

    def get_active_nodes(self, node_type: Optional[str] = None) -> List[Dict]:
        if node_type:
            node_ids = self.r.smembers(f"aurora:nodes:{node_type}") or []
        else:
            keys = self.r.keys("aurora:nodes:*")
            node_ids = [k.split(":")[-1] for k in keys if ":nodes:" in k]

        nodes = []
        for nid in node_ids:
            data = self.get_state(f"nodes:{nid}")
            if data:
                nodes.append(data)
        return nodes

    def get_nodes_by_capability(self, capability: str) -> List[Dict]:
        """Get all active nodes that have a specific capability."""
        node_ids = self.r.smembers(f"aurora:capability:{capability}") or []
        nodes = []
        for nid in node_ids:
            data = self.get_state(f"nodes:{nid}")
            if data:
                nodes.append(data)
        return nodes

    def get_workers(self) -> List[Dict]:
        return self.get_active_nodes(node_type="worker")

    # --- Messaging ---

    def send_to_node(self, target_node_id: str, message: Any):
        if isinstance(message, BaseModel):
            message = message.model_dump_json()
        elif isinstance(message, (dict, list)):
            message = json.dumps(message)
        channel = f"node:{target_node_id}"
        self.publish(channel, message)

    def broadcast_to_workers(self, message: Any):
        workers = self.get_workers()
        for w in workers:
            nid = w.get("node_id")
            if nid and nid != self.node_id:
                self.send_to_node(nid, message)

    def broadcast_to_capability(self, capability: str, message: Any):
        """Send a message to all nodes that have a specific capability."""
        nodes = self.get_nodes_by_capability(capability)
        for node in nodes:
            nid = node.get("node_id")
            if nid and nid != self.node_id:
                self.send_to_node(nid, message)

    # --- High-level methods ---

    def publish_event(self, event_type: str, data: Dict[str, Any], source: Optional[str] = None):
        msg = SwarmMessage(type=f"event.{event_type}", payload=data, source=source or self.node_id)
        self.publish_message("events", msg)
        self.publish("events", {"type": event_type, "data": data, "source": source or self.node_id})

    def publish_telemetry(self, metrics: Dict[str, Any], source: Optional[str] = None):
        msg = SwarmMessage(type="telemetry", payload=metrics, source=source or self.node_id)
        self.publish_message("telemetry", msg)

    def send_command(self, action: str, payload: Dict[str, Any] = None, target: Optional[str] = None):
        cmd = SwarmMessage(type="command", payload={"action": action, **(payload or {})}, source=self.node_id, target=target)
        if target:
            self.publish_message(f"commands:{target}", cmd)
        else:
            self.publish_message("commands", cmd)
            self.publish("swarm:commands", {"action": action, **(payload or {})})

    def send_sensing_command(self, action: str, **kwargs):
        self.send_command(action, payload=kwargs, target="sensing")

    # --- Subscription handling ---

    def subscribe(self, pattern: str, handler: Callable[[SwarmMessage], None]):
        if pattern not in self.handlers:
            self.handlers[pattern] = []
        self.handlers[pattern].append(handler)

    def start_listener(self, patterns: Optional[List[str]] = None):
        patterns = patterns or list(self.handlers.keys()) or ["aurora:events", "aurora:commands", "aurora:sensing:*", f"aurora:node:{self.node_id}"]
        for p in patterns:
            if p not in self._subscribed_patterns:
                self.pubsub.psubscribe(p)
                self._subscribed_patterns.append(p)

        logger.info(f"[MESH] Listener started on: {self._subscribed_patterns}")

        for message in self.pubsub.listen():
            if message["type"] in ("pmessage", "message"):
                try:
                    raw = message.get("data", "")
                    data = json.loads(raw) if isinstance(raw, str) else raw

                    if isinstance(data, dict) and "type" in data:
                        try:
                            msg = SwarmMessage(**data)
                        except:
                            msg = SwarmMessage(type="raw", payload={"raw": data})
                    else:
                        msg = SwarmMessage(type="raw", payload={"raw": data})

                    for pat, handlers in self.handlers.items():
                        if (pat.endswith("*") and msg.type.startswith(pat[:-1])) or pat == msg.type or pat in str(message.get("channel", "")):
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


if __name__ == "__main__":
    layer = CommsLayer(node_id="test-node")
    layer.register_node(
        node_type="worker",
        capabilities=["gpu_mining", "intensity_control", "pause_resume"],
        metadata={"gpus": 1}
    )
    print("Registered with capabilities.")
    print("Workers:", [n["node_id"] for n in layer.get_workers()])
    print("Nodes with intensity_control:", [n["node_id"] for n in layer.get_nodes_by_capability("intensity_control")])
