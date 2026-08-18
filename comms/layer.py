"""Aurora CommsLayer — Redis-backed mesh bus."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

import redis
from pydantic import BaseModel, Field

from .node_id import default_node_id

logger = logging.getLogger("aurora.comms")


class SwarmMessage(BaseModel):
    type: str
    payload: Any = None
    source: Optional[str] = None
    target: Optional[str] = None
    ts: float = Field(default_factory=time.time)


class CommsLayer:
    EVENT_HISTORY_KEY = "events:history"
    MAX_EVENTS = 200
    NODE_TTL = 180

    def __init__(self, redis_url: Optional[str] = None, node_id: Optional[str] = None):
        # Prefer host-local Redis for docker host-network solo; override via REDIS_URL / mesh join
        default = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        if default.startswith("redis://redis:"):
            default = "redis://127.0.0.1:6379/0"
        self.redis_url = redis_url or default
        self.node_id = node_id or default_node_id("node")
        self.r = redis.from_url(
            self.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        self.pubsub = None
        self.handlers: Dict[str, List[Callable[[SwarmMessage], None]]] = {}
        self._subscribed_patterns: List[str] = []
        try:
            self.pubsub = self.r.pubsub(ignore_subscribe_messages=True)
        except Exception as e:
            logger.warning(f"pubsub deferred: {e}")
            self.pubsub = None
        logger.info(f"CommsLayer initialized for node={self.node_id} url={self.redis_url}")

    def reconnect(self, redis_url: str) -> bool:
        """Point this process at a different Redis (LAN mesh leader)."""
        redis_url = (redis_url or "").strip()
        if not redis_url:
            return False
        try:
            client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            if not client.ping():
                return False
            old = self.r
            self.r = client
            self.redis_url = redis_url
            try:
                self.pubsub = self.r.pubsub(ignore_subscribe_messages=True)
            except Exception:
                self.pubsub = None
            try:
                old.close()
            except Exception:
                pass
            logger.info(f"CommsLayer reconnected node={self.node_id} url={redis_url}")
            return True
        except Exception as e:
            logger.warning(f"reconnect failed: {e}")
            return False

    def ping(self) -> bool:
        try:
            return bool(self.r.ping())
        except Exception as e:
            logger.debug(f"redis ping failed: {e}")
            return False

    def publish(self, channel: str, message: Any):
        if isinstance(message, (dict, list)):
            message = json.dumps(message)
        elif isinstance(message, BaseModel):
            message = message.model_dump_json()
        self.r.publish(f"aurora:{channel}", message)

    def publish_message(self, channel: str, msg: SwarmMessage):
        self.publish(channel, msg)
        if msg.type.startswith("event.") or msg.type == "event":
            self._log_event_to_history(msg)

    def set_state(self, key: str, value: Any, expire: int = 0):
        full_key = f"aurora:{key}"
        val = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        self.r.set(full_key, val)
        if expire and expire > 0:
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
            body = msg.model_dump_json() if hasattr(msg, "model_dump_json") else msg.json()
            pipe = self.r.pipeline()
            pipe.lpush(f"aurora:{self.EVENT_HISTORY_KEY}", body)
            pipe.ltrim(f"aurora:{self.EVENT_HISTORY_KEY}", 0, self.MAX_EVENTS - 1)
            pipe.execute()
        except Exception as e:
            logger.debug(f"event history: {e}")

    def get_recent_events(self, limit: int = 20) -> List[Dict]:
        try:
            raw = self.r.lrange(f"aurora:{self.EVENT_HISTORY_KEY}", 0, max(0, limit - 1)) or []
            out = []
            for item in raw:
                try:
                    out.append(json.loads(item))
                except Exception:
                    out.append({"raw": item})
            return out
        except Exception as e:
            logger.debug(f"get_recent_events: {e}")
            return []

    def register_node(
        self,
        node_type: str = "worker",
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        node_id: Optional[str] = None,
    ):
        nid = node_id or self.node_id
        payload = {
            "node_id": nid,
            "node_type": node_type,
            "capabilities": capabilities or [],
            "metadata": metadata or {},
            "ts": time.time(),
        }
        try:
            self.set_state(f"node:{nid}", payload, expire=self.NODE_TTL)
            self.r.sadd("aurora:nodes:active", nid)
        except Exception as e:
            logger.warning(f"register_node failed: {e}")

    def heartbeat(self, node_id: Optional[str] = None, metadata: Optional[Dict] = None):
        nid = node_id or self.node_id
        try:
            raw = self.get_state(f"node:{nid}") or {"node_id": nid}
            if not isinstance(raw, dict):
                raw = {"node_id": nid}
            if metadata:
                raw.setdefault("metadata", {}).update(metadata)
            raw["ts"] = time.time()
            self.set_state(f"node:{nid}", raw, expire=self.NODE_TTL)
            self.r.sadd("aurora:nodes:active", nid)
        except Exception as e:
            logger.debug(f"heartbeat: {e}")

    def get_active_nodes(self, node_type: Optional[str] = None, max_age: float = 120.0) -> List[Dict]:
        out: List[Dict] = []
        now = time.time()
        try:
            ids = list(self.r.smembers("aurora:nodes:active") or [])
            stale = []
            for nid in ids:
                if isinstance(nid, bytes):
                    nid = nid.decode()
                raw = self.get_state(f"node:{nid}")
                if not isinstance(raw, dict):
                    stale.append(nid)
                    continue
                ts = float(raw.get("ts") or 0)
                if max_age and ts and (now - ts) > max_age:
                    stale.append(nid)
                    continue
                if node_type and raw.get("node_type") != node_type:
                    continue
                out.append(raw)
            for nid in stale:
                try:
                    self.r.srem("aurora:nodes:active", nid)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"get_active_nodes: {e}")
        return out

    def get_nodes_with_capability(self, capability: str) -> List[Dict]:
        return [n for n in self.get_active_nodes() if capability in (n.get("capabilities") or [])]

    def get_workers(self) -> List[Dict]:
        return [
            n
            for n in self.get_active_nodes()
            if n.get("node_type") in ("worker", "dashboard", None)
            or "mining_engine" in (n.get("capabilities") or [])
            or "dashboard" in (n.get("capabilities") or [])
        ]

    def send_to_node(self, target_node_id: str, message: Any):
        if not isinstance(message, SwarmMessage):
            if isinstance(message, dict):
                message = SwarmMessage(
                    type="command",
                    payload=message,
                    source=self.node_id,
                    target=target_node_id,
                )
            else:
                message = SwarmMessage(type="command", payload=message, source=self.node_id, target=target_node_id)
        self.publish_message(f"command.node.{target_node_id}", message)

    def broadcast_to_workers(self, message: Any):
        if not isinstance(message, SwarmMessage):
            message = SwarmMessage(type="command", payload=message, source=self.node_id)
        self.publish_message("command.workers", message)
        for n in self.get_active_nodes():
            try:
                self.send_to_node(n.get("node_id"), message)
            except Exception:
                pass

    def publish_event(self, event_type: str, data: Dict[str, Any], source: Optional[str] = None):
        msg = SwarmMessage(type=f"event.{event_type}", payload=data, source=source or self.node_id)
        self.publish_message("events", msg)

    def publish_telemetry(self, metrics: Dict[str, Any], source: Optional[str] = None):
        msg = SwarmMessage(type="telemetry", payload=metrics, source=source or self.node_id)
        self.publish_message("telemetry", msg)

    def subscribe(self, pattern: str, handler: Callable[[SwarmMessage], None]):
        self.handlers.setdefault(pattern, []).append(handler)
        if pattern not in self._subscribed_patterns:
            self._subscribed_patterns.append(pattern)
            try:
                if self.pubsub:
                    self.pubsub.psubscribe(f"aurora:{pattern}")
            except Exception as e:
                logger.warning(f"subscribe failed: {e}")

    def start_listener(self, patterns: Optional[List[str]] = None):
        if patterns:
            for p in patterns:
                if p not in self._subscribed_patterns:
                    self.subscribe(p, lambda m: None)
