"""
Failure-domain topology for Aurora nodes.

A node is not just an id — it sits in nested failure domains.
Replication that ignores this is false availability.

Env (optional defaults for this process):
  AURORA_SITE, AURORA_POWER, AURORA_NETWORK, AURORA_RACK
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass(frozen=True)
class NodeTopology:
    node_id: str
    site: str = "unknown"
    power: str = "unknown"
    network: str = "unknown"
    rack: str = "unknown"
    extra: Dict[str, str] = field(default_factory=dict)

    def domains(self) -> Dict[str, str]:
        d = {
            "site": self.site,
            "power": self.power,
            "network": self.network,
            "rack": self.rack,
        }
        d.update(self.extra)
        return d

    def to_dict(self) -> Dict[str, Any]:
        return {"node_id": self.node_id, **self.domains()}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "NodeTopology":
        known = {"node_id", "site", "power", "network", "rack"}
        extra = {k: str(v) for k, v in d.items() if k not in known and k != "node_id"}
        return cls(
            node_id=str(d.get("node_id") or ""),
            site=str(d.get("site") or "unknown"),
            power=str(d.get("power") or "unknown"),
            network=str(d.get("network") or "unknown"),
            rack=str(d.get("rack") or "unknown"),
            extra=extra,
        )

    @classmethod
    def from_env(cls, node_id: str) -> "NodeTopology":
        return cls(
            node_id=node_id,
            site=os.getenv("AURORA_SITE", "unknown"),
            power=os.getenv("AURORA_POWER", "unknown"),
            network=os.getenv("AURORA_NETWORK", "unknown"),
            rack=os.getenv("AURORA_RACK", "unknown"),
        )


class TopologyRegistry:
    """Local view of node → topology (mesh-published or configured)."""

    def __init__(self):
        self._nodes: Dict[str, NodeTopology] = {}

    def upsert(self, topo: NodeTopology):
        if topo.node_id:
            self._nodes[topo.node_id] = topo

    def get(self, node_id: str) -> Optional[NodeTopology]:
        return self._nodes.get(node_id)

    def all(self) -> List[NodeTopology]:
        return list(self._nodes.values())

    def domain_values(self, domain: str, node_ids: List[str]) -> Set[str]:
        vals: Set[str] = set()
        for nid in node_ids:
            t = self._nodes.get(nid)
            if not t:
                vals.add("unknown")
                continue
            vals.add(t.domains().get(domain, "unknown"))
        return vals

    def to_list(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self._nodes.values()]


def publish_topology(comms: Any, topo: Optional[NodeTopology] = None) -> NodeTopology:
    """Publish this node's topology onto the mesh."""
    node_id = getattr(comms, "node_id", "unknown")
    t = topo or NodeTopology.from_env(node_id)
    try:
        comms.set_state(f"topo:{t.node_id}", t.to_dict(), expire=0)
        meta = {"topology": t.to_dict()}
        if hasattr(comms, "register_node"):
            try:
                comms.register_node(node_type="worker", capabilities=[], metadata=meta)
            except Exception:
                pass
    except Exception:
        pass
    return t


def load_topology_from_mesh(comms: Any, registry: TopologyRegistry):
    """Best-effort scan of topo:* keys."""
    try:
        keys = []
        if hasattr(comms, "r"):
            keys = list(comms.r.keys("aurora:topo:*") or [])
        for k in keys[:200]:
            key = k.replace("aurora:", "", 1) if str(k).startswith("aurora:") else k
            raw = comms.get_state(key)
            if isinstance(raw, dict) and raw.get("node_id"):
                registry.upsert(NodeTopology.from_dict(raw))
    except Exception:
        pass
