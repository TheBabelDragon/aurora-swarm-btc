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
        # Timeouts so a missing Redis does not hang the process forever
        self.r = redis.from_url(
            self.redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=5.0,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        try:
            self.pubsub = self.r.pubsub()
        except Exception as e:
            logger.warning(f"pubsub init deferred: {e}")
            self.pubsub = None
        self.handlers: Dict[str, List[Callable[[SwarmMessage], None]]] = {}
        self._subscribed_patterns: List[str] = []
        logger.info(f"CommsLayer initialized for node={self.node_id} url={self.redis_url}")

    def ping(self) -> bool:
        try:
            return bool(self.r.ping())
        except Exception as e:
            logger.debug(f"redis ping failed: {e}")
            return False

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
            entry = msg.model_dump_json() if hasattr(msg, "model_dump_json") else json.dumps(msg.dict())
            pipe = self.r.pipeline()
            pipe.lpush(f"aurora:{self.EVENT_HISTORY_KEY}", entry)
            pipe.ltrim(f"aurora:{self.EVENT_HISTORY_KEY}", 0, self.MAX_EVENTS - 1)
            pipe.execute()
        except Exception as e:
            logger.debug(f"event history: {e}")

    def get_recent_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            raw = self.r.lrange(f"aurora:{self.EVENT_HISTORY_KEY}", 0, max(0, limit - 1))
            out = []
            for item in raw or []:
                try:
                    out.append(json.loads(item))
                except Exception:
                    out.append({"raw": item})
            return out
        except Exception as e:
            logger.debug(f"get_recent_events: {e}")
            return []

    def subscribe(self, pattern: str, handler: Callable[[SwarmMessage], None]):
        if pattern not in self.handlers:
            self.handlers[pattern] = []
        self.handlers[pattern].append(handler)
        if pattern not in self._subscribed_patterns:
            self._subscribed_patterns.append(pattern)
            try:
                if self.pubsub is None:
                    self.pubsub = self.r.pubsub()
                self.pubsub.psubscribe(f"aurora:{pattern}")
            except Exception as e:
                logger.warning(f"subscribe failed: {e}")

    def register_node(
        self,
        node_type: str = "worker",
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        meta = metadata or {}
        payload = {
            "node_id": self.node_id,
            "node_type": node_type,
            "capabilities": capabilities or [],
            "metadata": meta,
            "ts": time.time(),
        }
        try:
            self.set_state(f"node:{self.node_id}", payload, expire=120)
            self.r.sadd("aurora:nodes:active", self.node_id)
        except Exception as e:
            logger.warning(f"register_node failed: {e}")

    def heartbeat(self, metadata: Optional[Dict[str, Any]] = None):
        try:
            raw = self.get_state(f"node:{self.node_id}") or {}
            if metadata:
                raw.setdefault("metadata", {}).update(metadata)
            raw["ts"] = time.time()
            self.set_state(f"node:{self.node_id}", raw, expire=120)
            self.r.sadd("aurora:nodes:active", self.node_id)
        except Exception as e:
            logger.debug(f"heartbeat: {e}")

    def get_active_nodes(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            ids = list(self.r.smembers("aurora:nodes:active") or [])
            for nid in ids:
                raw = self.get_state(f"node:{nid}")
                if isinstance(raw, dict):
                    out.append(raw)
                else:
                    out.append({"node_id": nid})
        except Exception as e:
            logger.debug(f"get_active_nodes: {e}")
        return out

    def get_workers(self) -> List[Dict[str, Any]]:
        nodes = self.get_active_nodes()
        return [n for n in nodes if n.get("node_type") == "worker" or "worker" in (n.get("capabilities") or [])]

    def get_nodes_by_capability(self, cap: str) -> List[Dict[str, Any]]:
        return [n for n in self.get_active_nodes() if cap in (n.get("capabilities") or [])]

    def broadcast_to_workers(self, payload: Dict[str, Any]):
        msg = SwarmMessage(type="command", payload=payload, source=self.node_id)
        self.publish_message("command.workers", msg)

    def send_to_node(self, node_id: str, payload: Dict[str, Any]):
        msg = SwarmMessage(type="command", payload=payload, source=self.node_id, target=node_id)
        self.publish_message(f"command.node.{node_id}", msg)
