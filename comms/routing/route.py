"""RouteManager - authenticated, expiring, policy-first route candidates."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .destination import Destination, DestinationKind
from .gateway import GatewayRegistry

logger = logging.getLogger("aurora.comms.routing.route")


@dataclass
class RoutePolicy:
    require_auth: bool = True
    allow_egress: bool = False
    prefer_transports: List[str] = field(default_factory=lambda: ["mesh", "tcp", "https"])
    max_candidates: int = 8
    prefer_fresh: bool = True


@dataclass
class RouteCandidate:
    route_id: str
    destination_key: str
    next_hop_id: str
    transport: str
    endpoint: str
    trust_ok: bool = False
    authorized: bool = False
    last_health_at: Optional[float] = None
    expires_at: float = 0.0
    latency_ms: Optional[float] = None
    failure_count: int = 0
    success_count: int = 0
    cooldown_until: float = 0.0
    last_failure_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    @property
    def eligible(self) -> bool:
        return self.trust_ok and self.authorized and not self.is_expired and not self.in_cooldown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route_id": self.route_id, "destination_key": self.destination_key,
            "next_hop_id": self.next_hop_id, "transport": self.transport,
            "endpoint": self.endpoint, "trust_ok": self.trust_ok,
            "authorized": self.authorized, "last_health_at": self.last_health_at,
            "expires_at": self.expires_at, "latency_ms": self.latency_ms,
            "failure_count": self.failure_count, "success_count": self.success_count,
            "cooldown_until": self.cooldown_until, "last_failure_reason": self.last_failure_reason,
            "eligible": self.eligible, "metadata": dict(self.metadata),
        }


class RouteManager:
    def __init__(self, *, gateway_registry: Optional[GatewayRegistry] = None,
                 default_ttl: float = 120.0,
                 node_lookup: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
                 hysteresis_hold: float = 5.0):
        self.gateways = gateway_registry or GatewayRegistry()
        self.default_ttl = default_ttl
        self._node_lookup = node_lookup
        self._hysteresis_hold = hysteresis_hold
        self._routes: Dict[str, RouteCandidate] = {}
        self._by_dest: Dict[str, List[str]] = {}
        self._last_selected: Dict[str, str] = {}
        self._last_select_at: Dict[str, float] = {}
        self._stats = {"selected": 0, "invalidated": 0, "success": 0, "failure": 0}

    def _dest_key(self, dest: Destination) -> str:
        return f"{dest.kind.value}:{dest.canonical_id}"

    def discover_routes(self, destination: Destination) -> List[RouteCandidate]:
        key = self._dest_key(destination)
        found: List[RouteCandidate] = []
        now = time.time()
        if destination.kind in (DestinationKind.NODE, DestinationKind.SERVICE):
            info = self._node_lookup(destination.canonical_id) if self._node_lookup else None
            if info or destination.kind == DestinationKind.SERVICE:
                rid = f"mesh:{destination.canonical_id}"
                rc = RouteCandidate(
                    route_id=rid, destination_key=key,
                    next_hop_id=destination.canonical_id, transport="mesh",
                    endpoint=f"mesh://{destination.canonical_id}",
                    trust_ok=True, authorized=True, last_health_at=now,
                    expires_at=now + self.default_ttl,
                    metadata={"source": "node_registry" if info else "service"},
                )
                self._store(rc)
                found.append(rc)
        for gw in self.gateways.list_gateways():
            if gw.is_expired:
                continue
            rid = f"gw:{gw.gateway_id}:{destination.canonical_id}"
            # Authenticated + fresh advertisement required for gateway routes
            trust = (gw.auth == "secret") and (not gw.is_expired)
            authorized = trust and bool(gw.supported_transports)
            rc = RouteCandidate(
                route_id=rid, destination_key=key, next_hop_id=gw.gateway_id,
                transport=gw.supported_transports[0] if gw.supported_transports else "mesh",
                endpoint=gw.from_ip or gw.node_id, trust_ok=trust, authorized=authorized,
                last_health_at=gw.last_health_at,
                expires_at=min(gw.expires_at, now + self.default_ttl),
                metadata={"gateway_node": gw.node_id, "egress_enabled": gw.egress_enabled,
                          "reachability": gw.reachability},
            )
            self._store(rc)
            found.append(rc)
        if destination.resolved_addresses and destination.kind in (
            DestinationKind.HOSTNAME, DestinationKind.IPV4, DestinationKind.IPV6,
        ):
            host = destination.hostname or destination.canonical_id
            port = destination.port or 443
            rid = f"direct:{host}:{port}"
            rc = RouteCandidate(
                route_id=rid, destination_key=key, next_hop_id="local", transport="tcp",
                endpoint=f"{destination.resolved_addresses[0]}:{port}",
                trust_ok=True, authorized=True, last_health_at=now,
                expires_at=destination.expires_at or (now + self.default_ttl),
                metadata={"hostname": destination.hostname,
                          "addresses": list(destination.resolved_addresses)},
            )
            self._store(rc)
            found.append(rc)
        return found

    def _store(self, rc: RouteCandidate):
        existing = self._routes.get(rc.route_id)
        if existing is not None:
            rc.failure_count = existing.failure_count
            rc.success_count = existing.success_count
            rc.cooldown_until = existing.cooldown_until
            rc.last_failure_reason = existing.last_failure_reason
            if existing.latency_ms is not None:
                rc.latency_ms = existing.latency_ms
            if existing.last_health_at and (
                rc.last_health_at is None or existing.last_health_at > rc.last_health_at
            ):
                rc.last_health_at = existing.last_health_at
        self._routes[rc.route_id] = rc
        lst = self._by_dest.setdefault(rc.destination_key, [])
        if rc.route_id not in lst:
            lst.append(rc.route_id)

    def select_route(self, destination: Destination, policy: Optional[RoutePolicy] = None) -> Optional[RouteCandidate]:
        policy = policy or RoutePolicy()
        key = self._dest_key(destination)
        self.discover_routes(destination)
        candidates: List[RouteCandidate] = []
        for rid in list(self._by_dest.get(key) or []):
            rc = self._routes.get(rid)
            if not rc or rc.is_expired:
                continue
            if policy.require_auth and not rc.trust_ok:
                continue
            if not rc.authorized or rc.in_cooldown:
                continue
            if not policy.allow_egress and rc.metadata.get("egress_enabled") and rc.transport not in ("mesh",):
                if rc.next_hop_id != "local" and rc.transport not in ("mesh",):
                    continue
            candidates.append(rc)
        if not candidates:
            return None
        last_id = self._last_selected.get(key)
        last_at = self._last_select_at.get(key, 0)
        if last_id and (time.time() - last_at) < self._hysteresis_hold:
            for c in candidates:
                if c.route_id == last_id and c.eligible and not c.in_cooldown:
                    self._stats["selected"] += 1
                    return c
        def sort_key(c: RouteCandidate):
            try:
                t_idx = policy.prefer_transports.index(c.transport)
            except ValueError:
                t_idx = 99
            return (t_idx, c.failure_count, -(c.last_health_at or 0))
        candidates.sort(key=sort_key)
        chosen = candidates[0]
        self._last_selected[key] = chosen.route_id
        self._last_select_at[key] = time.time()
        self._stats["selected"] += 1
        return chosen

    def report_route_success(self, route_id: str, metrics: Optional[Dict[str, Any]] = None):
        rc = self._routes.get(route_id)
        if not rc:
            return
        rc.success_count += 1
        rc.failure_count = max(0, rc.failure_count - 1)
        rc.last_health_at = time.time()
        rc.cooldown_until = 0.0
        if metrics and "latency_ms" in metrics:
            rc.latency_ms = float(metrics["latency_ms"])
        self._stats["success"] += 1

    def report_route_failure(self, route_id: str, reason: str):
        rc = self._routes.get(route_id)
        if not rc:
            return
        rc.failure_count += 1
        rc.last_failure_reason = reason
        backoff = min(60.0, (2 ** min(rc.failure_count, 5)) + (hash(route_id) % 7) * 0.1)
        rc.cooldown_until = time.time() + backoff
        self._stats["failure"] += 1

    def invalidate_route(self, route_id: str, reason: str):
        if route_id not in self._routes:
            return
        del self._routes[route_id]
        for key, ids in list(self._by_dest.items()):
            if route_id in ids:
                self._by_dest[key] = [i for i in ids if i != route_id]
        self._stats["invalidated"] += 1

    def refresh_routes(self) -> int:
        now = time.time()
        dead = [rid for rid, rc in self._routes.items() if rc.expires_at <= now]
        for rid in dead:
            self.invalidate_route(rid, "expired")
        return len(dead)

    def list_routes(self, destination: Optional[Destination] = None) -> List[RouteCandidate]:
        if destination is None:
            return list(self._routes.values())
        key = self._dest_key(destination)
        return [self._routes[i] for i in self._by_dest.get(key, []) if i in self._routes]

    def stats(self) -> Dict[str, int]:
        return dict(self._stats)
