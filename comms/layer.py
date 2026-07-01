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

    Mesh-aware design: every node that instantiates CommsLayer becomes part of the living node grid.
    - Self-registration + heartbeats
    - Targeted node-to-node messaging
    - Broadcast to groups (workers, etc.)
    - Event history
    - Full synergy with sensing, scheduler, API, and workers
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

    # --- Mesh / Node Grid Primitives ---

    def register_node(self, node_id: Optional[str] = None, node_type: str = "worker", metadata: Optional[Dict] = None, ttl: int = 90):
        """Join the mesh. Every node should call this on startup."""
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
        logger.info(f"[MESH] Node joined: {nid} (type={node_type})")

    def heartbeat(self, node_id: Optional[str] = None, metadata: Optional[Dict] = None):
        """Keep-alive for the mesh. Call periodically from every node."""
        nid = node_id or self.node_id
        self.register_node(nid, metadata=metadata)

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

    def get_workers(self) -> List[Dict]:
        return self.get_active_nodes(node_type="worker")

    def send_to_node(self, target_node_id: str, message: Any):
        """Direct targeted message to a specific node in the mesh (pubsub to its channel)."""
        if isinstance(message, BaseModel):
            message = message.model_dump_json()
        elif isinstance(message, (dict, list)):
            message = json.dumps(message)
        channel = f"node:{target_node_id}"
        self.publish(channel, message)
        logger.debug(f"[MESH] Sent direct to {target_node_id}")

    def broadcast_to_workers(self, message: Any):
        """Broadcast to all currently known workers in the mesh."""
        workers = self.get_workers()
        for w in workers:
            nid = w.get("node_id")
            if nid and nid != self.node_id:
                self.send_to_node(nid, message)

    # --- High-level Aurora methods (mesh-aware) ---

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

    # --- Subscription ---

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
    layer = CommsLayer(node_id="test-mesh-node")
    layer.register_node(node_type="worker", metadata={"gpus": 1})
    layer.heartbeat()
    print("Mesh node ready. Workers in grid:", [n["node_id"] for n in layer.get_workers()])
