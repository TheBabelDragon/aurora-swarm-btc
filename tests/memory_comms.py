"""In-memory CommsLayer stand-in. No Redis. Shared bus for multi-peer tests."""

from __future__ import annotations

import fnmatch
import json
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from comms.layer import SwarmMessage


class MemoryRedis:
    def __init__(self, store: Dict[str, Any], lists: Dict[str, List[str]]):
        self._store = store
        self._lists = lists

    def keys(self, pattern: str) -> List[str]:
        pat = pattern.replace("aurora:", "aurora:") if pattern.startswith("aurora:") else f"aurora:{pattern}"
        # Accept both raw and aurora-prefixed patterns.
        out = []
        for k in list(self._store.keys()):
            if fnmatch.fnmatch(k, pattern) or fnmatch.fnmatch(k, pat):
                out.append(k)
        return out

    def ping(self) -> bool:
        return True


class MemoryBus:
    def __init__(self):
        self.store: Dict[str, Any] = {}
        self.lists: Dict[str, List[str]] = defaultdict(list)
        self.handlers: Dict[str, List[Callable[[SwarmMessage], None]]] = defaultdict(list)


class MemoryComms:
    """Duck-typed CommsLayer used by AssetFabric / TorrentManager / AssetAnchor."""

    EVENT_HISTORY_KEY = "events:history"

    def __init__(self, node_id: str, bus: Optional[MemoryBus] = None):
        self.node_id = node_id
        self.bus = bus or MemoryBus()
        self.r = MemoryRedis(self.bus.store, self.bus.lists)
        self.handlers: Dict[str, List[Callable[[SwarmMessage], None]]] = defaultdict(list)
        self._nodes: Dict[str, Dict[str, Any]] = {}

    def ping(self) -> bool:
        return True

    def set_state(self, key: str, value: Any, expire: int = 0):
        full = key if str(key).startswith("aurora:") else f"aurora:{key}"
        val = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        self.bus.store[full] = val

    def get_state(self, key: str, default: Any = None) -> Any:
        full = key if str(key).startswith("aurora:") else f"aurora:{key}"
        val = self.bus.store.get(full)
        if val is None:
            return default
        try:
            return json.loads(val)
        except Exception:
            return val

    def publish(self, channel: str, message: Any):
        if isinstance(message, SwarmMessage):
            msg = message
        elif isinstance(message, dict):
            msg = SwarmMessage(**message) if "type" in message else SwarmMessage(type=channel, payload=message)
        else:
            msg = SwarmMessage(type=channel, payload=message)
        for handler in list(self.bus.handlers.get(channel, [])):
            handler(msg)

    def publish_message(self, channel: str, msg: SwarmMessage):
        self.publish(channel, msg)

    def subscribe(self, pattern: str, handler: Callable[[SwarmMessage], None]):
        self.bus.handlers[pattern].append(handler)
        self.handlers[pattern].append(handler)

    def register_node(self, node_type: str = "worker", capabilities: Optional[List[str]] = None, metadata: Optional[dict] = None):
        self._nodes[self.node_id] = {
            "node_id": self.node_id,
            "node_type": node_type,
            "capabilities": capabilities or [],
            "metadata": metadata or {},
        }
        self.set_state(f"node:{self.node_id}", self._nodes[self.node_id], expire=180)

    def get_active_nodes(self):
        return list(self._nodes.values())

    def get_nodes_by_capability(self, cap: str):
        return [n for n in self._nodes.values() if cap in (n.get("capabilities") or [])]

    def get_recent_events(self, limit: int = 20):
        return []
