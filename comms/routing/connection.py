"""Transport-neutral connection coordination."""

from __future__ import annotations

import logging
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .config import RoutingConfig
from .destination import Destination
from .policy import parse_cidrs, validate_resolved_for_egress
from .route import RouteCandidate, RouteManager, RoutePolicy

logger = logging.getLogger("aurora.comms.routing.connection")


@dataclass
class ConnectionResult:
    ok: bool
    route_id: Optional[str] = None
    transport: Optional[str] = None
    endpoint: Optional[str] = None
    error: Optional[str] = None
    error_category: Optional[str] = None
    latency_ms: Optional[float] = None
    next_retry_at: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "route_id": self.route_id, "transport": self.transport,
            "endpoint": self.endpoint, "error": self.error,
            "error_category": self.error_category, "latency_ms": self.latency_ms,
            "next_retry_at": self.next_retry_at, "details": dict(self.details),
        }


class ConnectionManager:
    def __init__(self, *, route_manager: RouteManager, config: Optional[RoutingConfig] = None,
                 mesh_send: Optional[Callable[[str, Any], bool]] = None):
        self.routes = route_manager
        self.config = config or RoutingConfig()
        self._mesh_send = mesh_send
        self._stats = {"connect_ok": 0, "connect_fail": 0, "timeout": 0,
                       "policy_denied": 0, "failover": 0}

    def connect(self, destination: Destination, *, policy: Optional[RoutePolicy] = None,
                probe_only: bool = False) -> ConnectionResult:
        policy = policy or RoutePolicy(allow_egress=False)
        max_retries = self.config.route_max_retries
        timeout = self.config.route_connect_timeout
        attempted: set = set()
        for attempt in range(max_retries + 1):
            route = self.routes.select_route(destination, policy)
            if route is None:
                return ConnectionResult(ok=False, error="no_eligible_route",
                                        error_category="unreachable", details={"attempts": attempt})
            if route.route_id in attempted:
                self.routes.report_route_failure(route.route_id, "duplicate_attempt")
                route = self.routes.select_route(destination, policy)
                if route is None or route.route_id in attempted:
                    return ConnectionResult(ok=False, error="no_alternate_route",
                                            error_category="unreachable")
            attempted.add(route.route_id)
            result = self._try_route(destination, route, timeout=timeout, probe_only=probe_only)
            if result.ok:
                self.routes.report_route_success(route.route_id, {"latency_ms": result.latency_ms})
                self._stats["connect_ok"] += 1
                return result
            self.routes.report_route_failure(route.route_id, result.error or "fail")
            self._stats["connect_fail"] += 1
            if result.error_category == "timeout":
                self._stats["timeout"] += 1
            if result.error_category == "policy":
                self._stats["policy_denied"] += 1
            if attempt < max_retries:
                self._stats["failover"] += 1
                self.routes.refresh_routes()
        return ConnectionResult(ok=False, error="all_routes_failed",
                                error_category="unreachable", details={"attempted": list(attempted)})

    def _try_route(self, destination: Destination, route: RouteCandidate, *,
                   timeout: float, probe_only: bool) -> ConnectionResult:
        if route.transport == "mesh":
            return self._mesh_connect(destination, route)
        if route.transport in ("tcp", "https"):
            return self._tcp_connect(destination, route, timeout=timeout,
                                     https=route.transport == "https")
        return ConnectionResult(ok=False, route_id=route.route_id, transport=route.transport,
                                error=f"unsupported_transport:{route.transport}",
                                error_category="unsupported")

    def _mesh_connect(self, destination: Destination, route: RouteCandidate) -> ConnectionResult:
        if self._mesh_send is None:
            return ConnectionResult(ok=False, route_id=route.route_id, transport="mesh",
                                    endpoint=route.endpoint, error="mesh_transport_unavailable",
                                    error_category="unreachable")
        t0 = time.time()
        try:
            ok = bool(self._mesh_send(destination.canonical_id, {"type": "probe"}))
            latency = (time.time() - t0) * 1000
            if ok:
                return ConnectionResult(ok=True, route_id=route.route_id, transport="mesh",
                                        endpoint=route.endpoint, latency_ms=latency)
            return ConnectionResult(ok=False, route_id=route.route_id, transport="mesh",
                                    error="mesh_send_failed", error_category="refused")
        except Exception as e:
            return ConnectionResult(ok=False, route_id=route.route_id, transport="mesh",
                                    error=str(e), error_category="refused")

    def _tcp_connect(self, destination: Destination, route: RouteCandidate, *,
                     timeout: float, https: bool) -> ConnectionResult:
        addrs = list(route.metadata.get("addresses") or destination.resolved_addresses or [])
        if not addrs and route.endpoint:
            addrs = [route.endpoint.rsplit(":", 1)[0]]
        port = destination.port or (443 if https else 80)
        if ":" in route.endpoint:
            try:
                port = int(route.endpoint.rsplit(":", 1)[-1])
            except ValueError:
                pass
        cidrs = parse_cidrs(self.config.egress_allowed_cidrs) if self.config.egress_allowed_cidrs else None
        if self.config.egress_allowed_cidrs or self.config.egress_allowed_ports:
            ok_pol, reason = validate_resolved_for_egress(
                addrs, port, allowed_cidrs=cidrs if cidrs else None,
                allowed_ports=self.config.egress_allowed_ports or None, deny_private=False)
            if not ok_pol:
                return ConnectionResult(ok=False, route_id=route.route_id, transport="tcp",
                                        error=reason, error_category="policy")
        if not addrs:
            return ConnectionResult(ok=False, route_id=route.route_id, error="no_addresses",
                                    error_category="dns")
        addr = addrs[0]
        t0 = time.time()
        try:
            sock = socket.create_connection((addr, port), timeout=timeout)
            if https:
                ctx = ssl.create_default_context()
                hostname = destination.hostname or destination.canonical_id
                try:
                    sock = ctx.wrap_socket(sock, server_hostname=hostname if destination.hostname else None)
                except ssl.SSLError as e:
                    sock.close()
                    return ConnectionResult(ok=False, route_id=route.route_id, transport="https",
                                            error=f"tls:{e}", error_category="tls")
            latency = (time.time() - t0) * 1000
            sock.close()
            return ConnectionResult(ok=True, route_id=route.route_id,
                                    transport="https" if https else "tcp",
                                    endpoint=f"{addr}:{port}", latency_ms=latency,
                                    details={"hostname": destination.hostname})
        except socket.timeout:
            return ConnectionResult(ok=False, route_id=route.route_id, transport="tcp",
                                    error="connect_timeout", error_category="timeout")
        except OSError as e:
            return ConnectionResult(ok=False, route_id=route.route_id, transport="tcp",
                                    error=str(e), error_category="refused")

    def https_probe(self, destination: Destination) -> ConnectionResult:
        policy = RoutePolicy(allow_egress=True, prefer_transports=["https", "tcp"])
        if destination.port is None:
            destination.port = 443
        if not destination.transport:
            destination.transport = "https"
        return self.connect(destination, policy=policy, probe_only=True)

    def stats(self) -> Dict[str, int]:
        return dict(self._stats)
