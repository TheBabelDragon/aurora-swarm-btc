"""Facade wiring DestinationResolver + registries into one optional service."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from .config import RoutingConfig, load_routing_config
from .connection import ConnectionManager
from .destination import DestinationResolver
from .diagnostics import NetworkDiagnostics
from .egress import EgressConfig, EgressGateway
from .gateway import GatewayRegistry
from .route import RouteManager

logger = logging.getLogger("aurora.comms.routing")


class DestinationRoutingService:
    """Independently testable; usable without mining, GPU, MetaField, or dashboard."""

    def __init__(self, *, config: Optional[RoutingConfig] = None,
                 node_lookup: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
                 mesh_send: Optional[Callable[[str, Any], bool]] = None,
                 known_services: Optional[Dict[str, Dict[str, Any]]] = None):
        self.config = config or load_routing_config()
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
        if self.config.egress_gateway_enabled and self.config.egress_port > 0:
            self.egress.start_listener()
        logger.info("destination routing enabled")

    def stop(self):
        self.egress.stop()


_service: Optional[DestinationRoutingService] = None


def get_routing_service() -> Optional[DestinationRoutingService]:
    return _service


def init_routing_service(**kwargs) -> DestinationRoutingService:
    global _service
    _service = DestinationRoutingService(**kwargs)
    if _service.config.enabled:
        _service.start()
    return _service
