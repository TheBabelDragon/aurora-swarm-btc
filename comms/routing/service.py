"""Facade wiring DestinationResolver + registries into one optional service."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from .config import RoutingConfig, load_routing_config
from .connection import ConnectionManager, ConnectionResult
from .destination import Destination, DestinationKind, DestinationResolver
from .diagnostics import NetworkDiagnostics
from .egress import EgressConfig, EgressGateway
from .gateway import GatewayRegistry
from .route import RouteManager, RoutePolicy

logger = logging.getLogger("aurora.comms.routing")


class DestinationRoutingService:
    """Independently testable; usable without mining, GPU, MetaField, or dashboard."""

    def __init__(self, *, config: Optional[RoutingConfig] = None,
                 node_lookup: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
                 mesh_send: Optional[Callable[[str, Any], bool]] = None,
                 known_services: Optional[Dict[str, Dict[str, Any]]] = None):
        self.config = config or load_routing_config()
        self._mesh_send = mesh_send
        self.gateways = GatewayRegistry()
        self.resolver = DestinationResolver(
            dns_timeout=self.config.dns_timeout,
            dns_cache_ttl_cap=self.config.dns_cache_ttl_cap,
            known_services=known_services or {
                "comms": {"transport": "mesh"}, "mining": {"transport": "mesh"},
                "dashboard": {"transport": "mesh"}, "sensing": {"transport": "mesh"},
                "metafield": {"transport": "mesh"},
            },
            node_lookup=node_lookup,
        )
        self.routes = RouteManager(
            gateway_registry=self.gateways, default_ttl=self.config.route_ttl,
            node_lookup=node_lookup,
        )
        self.connections = ConnectionManager(
            route_manager=self.routes, config=self.config, mesh_send=mesh_send,
        )
        self.egress = EgressGateway(EgressConfig(
            enabled=self.config.egress_gateway_enabled,
            bind_host=self.config.egress_bind_host, port=self.config.egress_port,
            allowed_cidrs=list(self.config.egress_allowed_cidrs),
            allowed_ports=set(self.config.egress_allowed_ports),
            max_connections=self.config.egress_max_connections,
            connect_timeout=self.config.route_connect_timeout,
            deny_private=self.config.deny_private_for_egress,
        ))
        self.diagnostics = NetworkDiagnostics(
            resolver=self.resolver, routes=self.routes, gateways=self.gateways,
            connections=self.connections, egress=self.egress, config=self.config,
        )
        problems = self.config.validate()
        if problems:
            logger.warning("routing config issues: %s", problems)

    def start(self):
        if not self.config.enabled:
            logger.info("destination routing disabled (AURORA_DESTINATION_ROUTING_ENABLED)")
            return
        # Relay/proxy is not implemented in v0.1; start_listener always refuses.
        if self.config.egress_gateway_enabled:
            self.egress.start_listener()  # logs relay_not_implemented
        logger.info("destination routing enabled (egress relay not implemented)")

    def stop(self):
        self.egress.stop()

    def resolve(self, target: str) -> Dict[str, Any]:
        """Resolve a target string via diagnostics (read-only)."""
        return self.diagnostics.resolve_target(target)

    def mesh_send_to(self, target: str, payload: Any = None) -> Dict[str, Any]:
        """Resolve *target*, require a mesh route, deliver via mesh_send.

        Mesh-only application path. Does not open TCP/HTTPS or egress.

        Outcome fields (only claimed when evidence exists):
          send_attempted       — transport call was invoked
          send_accepted        — transport accepted the message for publish
          recipient_acknowledged — transport provided recipient ack (rare)
          application_delivered — application-level delivery confirmed (rare)
          result_kind          — send_accepted | recipient_acknowledged |
                                 application_delivered | unreachable | failed

        A bare True return from mesh_send is treated as send_accepted only
        (publish succeeded), never as recipient acknowledgment.
        """
        dest, err = self.resolver.try_resolve(target)
        if err or dest is None:
            return {"ok": False, "error": err or "unresolved", "target": target,
                    "result_kind": "unreachable",
                    "send_attempted": False, "send_accepted": False,
                    "recipient_acknowledged": False, "application_delivered": False}
        if dest.kind not in (DestinationKind.NODE, DestinationKind.SERVICE):
            return {
                "ok": False, "error": "mesh_send_requires_node_or_service",
                "target": target, "kind": dest.kind.value,
                "result_kind": "unreachable",
                "send_attempted": False, "send_accepted": False,
                "recipient_acknowledged": False, "application_delivered": False,
                "note": "Use resolve/probe for hostname/IP; mesh delivery is node/service only",
            }
        if self._mesh_send is None:
            return {"ok": False, "error": "mesh_transport_unavailable", "target": target,
                    "result_kind": "unreachable",
                    "send_attempted": False, "send_accepted": False,
                    "recipient_acknowledged": False, "application_delivered": False}
        policy = RoutePolicy(allow_egress=False, prefer_transports=["mesh"])
        route = self.routes.select_route(dest, policy)
        if route is None or route.transport != "mesh":
            return {
                "ok": False, "error": "no_mesh_route",
                "target": target, "destination": dest.to_dict(),
                "result_kind": "unreachable",
                "send_attempted": False, "send_accepted": False,
                "recipient_acknowledged": False, "application_delivered": False,
            }
        body = payload if payload is not None else {"type": "route_send"}
        try:
            raw = self._mesh_send(dest.canonical_id, body)
        except Exception as e:
            self.routes.report_route_failure(route.route_id, str(e)[:80])
            return {
                "ok": False, "error": str(e)[:200], "target": target,
                "route_id": route.route_id, "result_kind": "failed",
                "send_attempted": True, "send_accepted": False,
                "recipient_acknowledged": False, "application_delivered": False,
            }

        send_accepted = False
        recipient_ack = False
        app_delivered = False
        if isinstance(raw, dict):
            send_accepted = bool(raw.get("send_accepted", raw.get("ok", False)))
            recipient_ack = bool(raw.get("recipient_acknowledged", False))
            app_delivered = bool(raw.get("application_delivered", False))
        else:
            send_accepted = bool(raw)

        if not send_accepted and not recipient_ack and not app_delivered:
            self.routes.report_route_failure(route.route_id, "mesh_send_failed")
            return {
                "ok": False, "error": "mesh_send_failed", "target": target,
                "route_id": route.route_id, "result_kind": "failed",
                "send_attempted": True, "send_accepted": False,
                "recipient_acknowledged": False, "application_delivered": False,
            }

        self.routes.report_route_success(route.route_id)
        if app_delivered:
            kind = "application_delivered"
        elif recipient_ack:
            kind = "recipient_acknowledged"
        else:
            kind = "send_accepted"
        return {
            "ok": True,
            "target": target,
            "node_id": dest.canonical_id,
            "route_id": route.route_id,
            "transport": "mesh",
            "result_kind": kind,
            "send_attempted": True,
            "send_accepted": send_accepted or recipient_ack or app_delivered,
            "recipient_acknowledged": recipient_ack,
            "application_delivered": app_delivered,
            "destination": dest.to_dict(),
            "note": (
                "send_accepted means transport published; not recipient ack"
                if kind == "send_accepted" else None
            ),
        }

    def resolve_and_probe(self, target: str) -> Dict[str, Any]:
        """Resolve + connection probe (mesh ack or TCP/HTTPS handshake). Not delivery."""
        dest, err = self.resolver.try_resolve(target)
        if err or dest is None:
            return {"ok": False, "error": err or "unresolved", "target": target,
                    "result_kind": "unreachable"}
        policy = RoutePolicy(allow_egress=False)
        result: ConnectionResult = self.connections.connect(dest, policy=policy, probe_only=True)
        out = result.to_dict()
        out["target"] = target
        out["destination"] = dest.to_dict()
        return out


_service: Optional[DestinationRoutingService] = None


def get_routing_service() -> Optional[DestinationRoutingService]:
    return _service


def init_routing_service(**kwargs) -> DestinationRoutingService:
    global _service
    _service = DestinationRoutingService(**kwargs)
    if _service.config.enabled:
        _service.start()
    return _service
