"""Read-only network diagnostics for dashboard/API."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .config import RoutingConfig
from .connection import ConnectionManager
from .destination import DestinationResolver
from .egress import EgressGateway
from .gateway import GatewayRegistry
from .route import RouteManager, RoutePolicy


class NetworkDiagnostics:
    def __init__(self, *, resolver: DestinationResolver, routes: RouteManager,
                 gateways: GatewayRegistry, connections: ConnectionManager,
                 egress: EgressGateway, config: RoutingConfig):
        self.resolver = resolver
        self.routes = routes
        self.gateways = gateways
        self.connections = connections
        self.egress = egress
        self.config = config

    def resolve_target(self, target: str) -> Dict[str, Any]:
        dest, err = self.resolver.try_resolve(target)
        if err or dest is None:
            return {"ok": False, "target": target, "error": err or "unresolved",
                    "resolved": False, "reachable_hint": "unresolved"}
        candidates = self.routes.discover_routes(dest)
        eligible = [c for c in candidates if c.eligible]
        selected = self.routes.select_route(dest, RoutePolicy())
        reach = "unreachable"
        if eligible:
            if any(c.transport == "mesh" for c in eligible):
                reach = "mesh_reachable"
            elif any(c.next_hop_id == "local" for c in eligible):
                reach = "locally_reachable"
            elif any(c.metadata.get("egress_enabled") for c in eligible):
                reach = "gateway_reachable"
            else:
                reach = "route_candidates"
        return {
            "ok": True, "target": target, "resolved": True,
            "destination": dest.to_dict(),
            "candidate_count": len(candidates), "eligible_count": len(eligible),
            "selected_route": selected.to_dict() if selected else None,
            "selection_reason": (
                "no_eligible_route" if selected is None
                else f"policy_then_transport_freshness:{selected.transport}"
            ),
            "reachable_hint": reach, "ts": time.time(),
        }

    def list_routes(self, target: Optional[str] = None) -> Dict[str, Any]:
        if target:
            dest, err = self.resolver.try_resolve(target)
            if err or dest is None:
                return {"ok": False, "error": err, "routes": []}
            routes = self.routes.list_routes(dest)
        else:
            routes = self.routes.list_routes()
        return {"ok": True, "routes": [r.to_dict() for r in routes],
                "count": len(routes), "stats": self.routes.stats()}

    def list_gateways(self) -> Dict[str, Any]:
        gws = self.gateways.list_gateways()
        return {"ok": True, "gateways": [g.to_dict() for g in gws],
                "count": len(gws), "stats": self.gateways.stats()}

    def network_status(self) -> Dict[str, Any]:
        return {
            "ok": True, "routing_enabled": self.config.enabled,
            "gateway_advertise_enabled": self.config.gateway_advertise_enabled,
            "egress": self.egress.status(),
            "resolver_stats": self.resolver.stats(),
            "route_stats": self.routes.stats(),
            "gateway_stats": self.gateways.stats(),
            "connection_stats": self.connections.stats(),
            "ts": time.time(),
        }
