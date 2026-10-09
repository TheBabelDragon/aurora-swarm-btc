"""Transport-neutral connection coordination.

Separates reachability *probes* from application *delivery*.
Policy is enforced on every public-egress path regardless of allow-list config.
"""

from __future__ import annotations

import logging
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .config import RoutingConfig
from .destination import Destination
from .policy import parse_cidrs, validate_resolved_for_egress, validate_selected_address
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
    result_kind: str = "probe"  # probe | mesh_ack | unreachable
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "route_id": self.route_id, "transport": self.transport,
            "endpoint": self.endpoint, "error": self.error,
            "error_category": self.error_category, "latency_ms": self.latency_ms,
            "next_retry_at": self.next_retry_at, "result_kind": self.result_kind,
            "details": dict(self.details),
        }


class ConnectionManager:
    def __init__(self, *, route_manager: RouteManager, config: Optional[RoutingConfig] = None,
                 mesh_send: Optional[Callable[[str, Any], bool]] = None):
        self.routes = route_manager
        self.config = config or RoutingConfig()
        self._mesh_send = mesh_send
        self._stats = {"connect_ok": 0, "connect_fail": 0, "timeout": 0,
                       "policy_denied": 0, "failover": 0, "probe_ok": 0}

    def connect(self, destination: Destination, *, policy: Optional[RoutePolicy] = None,
                probe_only: bool = True) -> ConnectionResult:
        policy = policy or RoutePolicy(allow_egress=False)
        max_retries = self.config.route_max_retries
        timeout = self.config.route_connect_timeout
        attempted: set = set()
        last_result: Optional[ConnectionResult] = None

        for attempt in range(max_retries + 1):
            route = self.routes.select_route(destination, policy)
            if route is None:
                if last_result is not None:
                    return last_result
                return ConnectionResult(ok=False, error="no_eligible_route",
                                        error_category="unreachable", result_kind="unreachable",
                                        details={"attempts": attempt})
            if route.route_id in attempted:
                self.routes.report_route_failure(route.route_id, "duplicate_attempt")
                route = self.routes.select_route(destination, policy)
                if route is None or route.route_id in attempted:
                    if last_result is not None:
                        return last_result
                    return ConnectionResult(ok=False, error="no_alternate_route",
                                            error_category="unreachable", result_kind="unreachable")
            attempted.add(route.route_id)
            result = self._try_route(destination, route, timeout=timeout, probe_only=probe_only)
            last_result = result
            if result.ok:
                self.routes.report_route_success(route.route_id, {"latency_ms": result.latency_ms})
                self._stats["connect_ok"] += 1
                if result.result_kind == "probe":
                    self._stats["probe_ok"] += 1
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

        if last_result is not None:
            last_result.details = dict(last_result.details or {})
            last_result.details["attempted"] = list(attempted)
            return last_result
        return ConnectionResult(ok=False, error="all_routes_failed",
                                error_category="unreachable", result_kind="unreachable",
                                details={"attempted": list(attempted)})

    def _try_route(self, destination: Destination, route: RouteCandidate, *,
                   timeout: float, probe_only: bool) -> ConnectionResult:
        if route.transport == "mesh":
            return self._mesh_connect(destination, route, probe_only=probe_only)
        if route.transport in ("tcp", "https"):
            return self._tcp_probe(destination, route, timeout=timeout,
                                   https=route.transport == "https")
        return ConnectionResult(ok=False, route_id=route.route_id, transport=route.transport,
                                error=f"unsupported_transport:{route.transport}",
                                error_category="unsupported", result_kind="unreachable")

    def _mesh_connect(self, destination: Destination, route: RouteCandidate,
                      *, probe_only: bool) -> ConnectionResult:
        if self._mesh_send is None:
            return ConnectionResult(ok=False, route_id=route.route_id, transport="mesh",
                                    endpoint=route.endpoint, error="mesh_transport_unavailable",
                                    error_category="unreachable", result_kind="unreachable")
        t0 = time.time()
        try:
            ok = bool(self._mesh_send(destination.canonical_id, {"type": "probe"}))
            latency = (time.time() - t0) * 1000
            if ok:
                return ConnectionResult(ok=True, route_id=route.route_id, transport="mesh",
                                        endpoint=route.endpoint, latency_ms=latency,
                                        result_kind="probe", details={"probe_only": probe_only})
            return ConnectionResult(ok=False, route_id=route.route_id, transport="mesh",
                                    error="mesh_send_failed", error_category="refused",
                                    result_kind="unreachable")
        except Exception as e:
            return ConnectionResult(ok=False, route_id=route.route_id, transport="mesh",
                                    error=str(e), error_category="refused", result_kind="unreachable")

    def _policy_check(self, addrs: list, port: int):
        deny_private = getattr(self.config, "deny_private_for_egress", True)
        cidrs = (parse_cidrs(self.config.egress_allowed_cidrs)
                 if self.config.egress_allowed_cidrs else None)
        ports = self.config.egress_allowed_ports or None
        return validate_resolved_for_egress(
            addrs, port, allowed_cidrs=cidrs if cidrs else None,
            allowed_ports=ports, deny_private=deny_private)

    def _tcp_probe(self, destination: Destination, route: RouteCandidate, *,
                   timeout: float, https: bool) -> ConnectionResult:
        addrs = list(route.metadata.get("addresses") or destination.resolved_addresses or [])
        if not addrs and route.endpoint:
            host_part = route.endpoint.rsplit(":", 1)[0]
            if host_part.startswith("[") and host_part.endswith("]"):
                host_part = host_part[1:-1]
            addrs = [host_part]
        port = destination.port or (443 if https else 80)
        if ":" in (route.endpoint or ""):
            try:
                port = int(route.endpoint.rsplit(":", 1)[-1])
            except ValueError:
                pass
        if not addrs:
            return ConnectionResult(ok=False, route_id=route.route_id, error="no_addresses",
                                    error_category="dns", result_kind="unreachable")
        ok_pol, reason = self._policy_check(addrs, port)
        if not ok_pol:
            return ConnectionResult(ok=False, route_id=route.route_id, transport="tcp",
                                    error=reason, error_category="policy", result_kind="unreachable",
                                    details={"addresses_checked": addrs})
        last_err = "no_addresses"
        for addr in addrs:
            ok_sel, sel_reason = validate_selected_address(
                addr, port,
                allowed_cidrs=(parse_cidrs(self.config.egress_allowed_cidrs)
                               if self.config.egress_allowed_cidrs else None),
                allowed_ports=self.config.egress_allowed_ports or None,
                deny_private=getattr(self.config, "deny_private_for_egress", True))
            if not ok_sel:
                last_err = sel_reason
                continue
            t0 = time.time()
            try:
                sock = socket.create_connection((addr, port), timeout=timeout)
                if https:
                    ctx = ssl.create_default_context()
                    hostname = destination.hostname or destination.canonical_id
                    try:
                        sock = ctx.wrap_socket(
                            sock, server_hostname=hostname if destination.hostname else None)
                    except ssl.SSLError as e:
                        sock.close()
                        return ConnectionResult(ok=False, route_id=route.route_id, transport="https",
                                                error=f"tls:{e}", error_category="tls",
                                                result_kind="unreachable")
                latency = (time.time() - t0) * 1000
                sock.close()
                return ConnectionResult(
                    ok=True, route_id=route.route_id,
                    transport="https" if https else "tcp",
                    endpoint=f"{addr}:{port}", latency_ms=latency, result_kind="probe",
                    details={"hostname": destination.hostname, "probe_only": True,
                             "note": "tcp/https handshake only; not application delivery"})
            except socket.timeout:
                last_err = "connect_timeout"
                continue
            except OSError as e:
                last_err = str(e)
                continue
        category = ("timeout" if last_err == "connect_timeout"
                    else "policy" if last_err in ("blocked_private_or_reserved",
                                                   "not_in_allowed_cidrs", "port_denied")
                    else "refused")
        return ConnectionResult(ok=False, route_id=route.route_id, transport="tcp",
                                error=last_err, error_category=category, result_kind="unreachable")

    def https_probe(self, destination: Destination) -> ConnectionResult:
        policy = RoutePolicy(allow_egress=True, prefer_transports=["https", "tcp"])
        if destination.port is None:
            destination.port = 443
        if not destination.transport:
            destination.transport = "https"
        return self.connect(destination, policy=policy, probe_only=True)

    def stats(self) -> Dict[str, int]:
        return dict(self._stats)
