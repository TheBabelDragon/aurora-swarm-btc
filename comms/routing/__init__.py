"""Aurora destination discovery & gateway routing (v0.1 + Autonomic Fabric Phase 1).

Local-first, transport-independent destination resolution and route selection
integrated with CommsLayer. Does not replace Redis mesh discovery or require
public internet connectivity for local mesh operation.

Phase 1 adds precise delivery states, message envelopes, peer health, and
authenticated acknowledgments without rewriting the existing route engine.
"""

from .destination import Destination, DestinationKind, DestinationResolver
from .gateway import GatewayAdvertisement, GatewayRegistry
from .route import RouteCandidate, RouteManager, RoutePolicy
from .connection import ConnectionManager, ConnectionResult
from .egress import EgressGateway, EgressConfig
from .diagnostics import NetworkDiagnostics
from .config import RoutingConfig, load_routing_config
from .delivery import (
    AckKind,
    Acknowledgment,
    DedupCache,
    DeliveryOutcome,
    DeliveryState,
    MessageEnvelope,
    PeerHealth,
    PeerHealthTracker,
)

__all__ = [
    "Destination",
    "DestinationKind",
    "DestinationResolver",
    "GatewayAdvertisement",
    "GatewayRegistry",
    "RouteCandidate",
    "RouteManager",
    "RoutePolicy",
    "ConnectionManager",
    "ConnectionResult",
    "EgressGateway",
    "EgressConfig",
    "NetworkDiagnostics",
    "RoutingConfig",
    "load_routing_config",
    "DeliveryState",
    "AckKind",
    "MessageEnvelope",
    "Acknowledgment",
    "DedupCache",
    "PeerHealth",
    "PeerHealthTracker",
    "DeliveryOutcome",
]
