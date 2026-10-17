"""Facade wiring DestinationResolver + registries into one optional service.

Phase 1 Autonomic Fabric extensions:
  - Precise delivery states (ACCEPTED / FORWARDED / DELIVERED / FAILED / UNKNOWN)
  - Message IDs, bounded dedup, expiry, hop limits, replay protection
  - Peer health tracking and alternate-route recovery with hysteresis
  - Authenticated hop vs destination acknowledgments
  - Existing mesh_send_to API remains compatible
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

from .config import RoutingConfig, load_routing_config
from .connection import ConnectionManager, ConnectionResult
from .delivery import (
    AckKind,
    Acknowledgment,
    DedupCache,
    DeliveryOutcome,
    DeliveryState,
    MessageEnvelope,
    PeerHealthTracker,
)
from .destination import Destination, DestinationKind, DestinationResolver
from .diagnostics import NetworkDiagnostics
from .egress import EgressConfig, EgressGateway
from .gateway import GatewayRegistry
from .route import RouteManager, RoutePolicy

logger = logging.getLogger("aurora.comms.routing")


def _mesh_secret() -> Optional[bytes]:
    raw = (os.getenv("AURORA_MESH_SECRET") or "").strip()
    if not raw:
        return None
    return raw.encode("utf-8")


class DestinationRoutingService:
    """Independently testable; usable without mining, GPU, MetaField, or dashboard."""

    def __init__(
        self,
        *,
        config: Optional[RoutingConfig] = None,
        node_lookup: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        mesh_send: Optional[Callable[[str, Any], bool]] = None,
        known_services: Optional[Dict[str, Dict[str, Any]]] = None,
        local_node_id: str = "local",
    ):
        self.config = config or load_routing_config()
        self._mesh_send = mesh_send
        self._local_node_id = local_node_id or "local"
        self.gateways = GatewayRegistry()
        self.resolver = DestinationResolver(
            dns_timeout=self.config.dns_timeout,
            dns_cache_ttl_cap=self.config.dns_cache_ttl_cap,
            known_services=known_services
            or {
                "comms": {"transport": "mesh"},
                "mining": {"transport": "mesh"},
                "dashboard": {"transport": "mesh"},
                "sensing": {"transport": "mesh"},
                "metafield": {"transport": "mesh"},
            },
            node_lookup=node_lookup,
        )
        self.routes = RouteManager(
            gateway_registry=self.gateways,
            default_ttl=self.config.route_ttl,
            node_lookup=node_lookup,
        )
        self.connections = ConnectionManager(
            route_manager=self.routes,
            config=self.config,
            mesh_send=mesh_send,
        )
        self.egress = EgressGateway(
            EgressConfig(
                enabled=self.config.egress_gateway_enabled,
                bind_host=self.config.egress_bind_host,
                port=self.config.egress_port,
                allowed_cidrs=list(self.config.egress_allowed_cidrs),
                allowed_ports=set(self.config.egress_allowed_ports),
                max_connections=self.config.egress_max_connections,
                connect_timeout=self.config.route_connect_timeout,
                deny_private=self.config.deny_private_for_egress,
            )
        )
        self.diagnostics = NetworkDiagnostics(
            resolver=self.resolver,
            routes=self.routes,
            gateways=self.gateways,
            connections=self.connections,
            egress=self.egress,
            config=self.config,
        )
        self.dedup = DedupCache(max_entries=4096, default_ttl=300.0)
        self.peer_health = PeerHealthTracker()
        self._delivery_log: List[Dict[str, Any]] = []
        self._max_delivery_log = 128
        problems = self.config.validate()
        if problems:
            logger.warning("routing config issues: %s", problems)

    def start(self):
        if not self.config.enabled:
            logger.info("destination routing disabled (AURORA_DESTINATION_ROUTING_ENABLED)")
            return
        if self.config.egress_gateway_enabled:
            self.egress.start_listener()
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
          state                — ACCEPTED | FORWARDED | DELIVERED | FAILED | UNKNOWN
          message_id           — unique id for this envelope

        A bare True return from mesh_send is treated as send_accepted only
        (publish succeeded), never as recipient acknowledgment.
        """
        outcome = self._deliver_with_recovery(target, payload)
        result = outcome.to_dict()
        result["ok"] = outcome.state in (
            DeliveryState.ACCEPTED,
            DeliveryState.FORWARDED,
            DeliveryState.DELIVERED,
        )
        result["target"] = target
        result["send_attempted"] = outcome.attempts > 0 or bool(
            outcome.failure_reason
            not in (
                "unresolved",
                "mesh_transport_unavailable",
                "mesh_send supports node/service only",
                "no_mesh_route",
            )
        )
        if outcome.attempts == 0 and outcome.failure_reason in (
            "unresolved",
            "mesh_transport_unavailable",
            "mesh_send supports node/service only",
            "no_mesh_route",
        ):
            result["send_attempted"] = False
        if outcome.details.get("destination"):
            result["destination"] = outcome.details["destination"]
        if outcome.details.get("node_id"):
            result["node_id"] = outcome.details["node_id"]
        if outcome.failure_reason:
            result["error"] = outcome.failure_reason
        if outcome.state == DeliveryState.ACCEPTED and not outcome.destination_ack:
            result["note"] = "send_accepted means transport published; not recipient ack"
        self._record_outcome(result)
        return result

    def _deliver_with_recovery(
        self, target: str, payload: Any = None
    ) -> DeliveryOutcome:
        dest, err = self.resolver.try_resolve(target)
        if err or dest is None:
            return DeliveryOutcome(
                state=DeliveryState.FAILED,
                message_id="",
                failure_reason=err or "unresolved",
                details={"result_kind": "unreachable"},
            )
        if dest.kind not in (DestinationKind.NODE, DestinationKind.SERVICE):
            return DeliveryOutcome(
                state=DeliveryState.FAILED,
                message_id="",
                failure_reason="mesh_send supports node/service only",
                details={
                    "destination": dest.to_dict(),
                    "result_kind": "unreachable",
                },
            )
        if self._mesh_send is None:
            return DeliveryOutcome(
                state=DeliveryState.FAILED,
                message_id="",
                failure_reason="mesh_transport_unavailable",
                details={"result_kind": "unreachable"},
            )

        body = payload if payload is not None else {"type": "route_send"}
        if not isinstance(body, dict):
            body = {"data": body}

        envelope = MessageEnvelope(
            message_id="",
            destination_id=dest.canonical_id,
            source_id=self._local_node_id,
            payload=body,
            expires_at=time.time() + max(30.0, self.config.route_ttl),
            hop_limit=8,
        )
        secret = _mesh_secret()
        if secret:
            envelope.sign(secret)

        if not self.dedup.check_and_record(
            envelope.message_id,
            envelope.nonce,
            ttl=max(1.0, envelope.expires_at - time.time()),
        ):
            return DeliveryOutcome(
                state=DeliveryState.FAILED,
                message_id=envelope.message_id,
                failure_reason="duplicate_or_replay",
            )

        policy = RoutePolicy(allow_egress=False, prefer_transports=["mesh"])
        max_attempts = max(1, self.config.route_max_retries + 1)
        selected: List[str] = []
        rejected: List[Dict[str, str]] = []
        last_error = "no_mesh_route"
        attempts = 0

        for _ in range(max_attempts):
            route = self.routes.select_route(dest, policy)
            if route is None or route.transport != "mesh":
                break
            if route.route_id in selected:
                self.routes.report_route_failure(route.route_id, "already_tried")
                rejected.append({"route_id": route.route_id, "reason": "already_tried"})
                continue

            health = self.peer_health.get(route.next_hop_id)
            if health.unreachable_confirmed:
                rejected.append(
                    {"route_id": route.route_id, "reason": "peer_unreachable_confirmed"}
                )
                self.routes.report_route_failure(route.route_id, "peer_unreachable")
                continue
            if health.is_temporarily_lost and health.consecutive_failures >= 3:
                rejected.append(
                    {"route_id": route.route_id, "reason": "peer_temporary_loss"}
                )
                continue

            selected.append(route.route_id)
            attempts += 1
            t0 = time.time()

            transport_body = {
                **envelope.payload,
                "_aurora_envelope": {
                    "message_id": envelope.message_id,
                    "source_id": envelope.source_id,
                    "destination_id": envelope.destination_id,
                    "created_at": envelope.created_at,
                    "expires_at": envelope.expires_at,
                    "hop_limit": envelope.hop_limit,
                    "hop_count": envelope.hop_count,
                    "nonce": envelope.nonce,
                    "signature": envelope.signature,
                },
            }

            try:
                raw = self._mesh_send(dest.canonical_id, transport_body)
            except Exception as e:
                reason = str(e)[:80]
                self.routes.report_route_failure(route.route_id, reason)
                self.peer_health.record_failure(route.next_hop_id, reason)
                rejected.append({"route_id": route.route_id, "reason": reason})
                last_error = reason
                continue

            latency_ms = (time.time() - t0) * 1000.0
            send_accepted = False
            recipient_ack = False
            app_delivered = False
            hop_ack = False

            if isinstance(raw, dict):
                send_accepted = bool(raw.get("send_accepted", raw.get("ok", False)))
                recipient_ack = bool(raw.get("recipient_acknowledged", False))
                app_delivered = bool(raw.get("application_delivered", False))
                hop_ack = bool(raw.get("hop_acknowledged", False))
                if raw.get("ack") and isinstance(raw["ack"], dict):
                    ack = Acknowledgment.from_dict(raw["ack"])
                    if secret and not ack.verify(secret):
                        recipient_ack = False
                        app_delivered = False
                    elif ack.message_id == envelope.message_id:
                        if ack.ack_kind == AckKind.DESTINATION:
                            recipient_ack = True
                            if ack.state == DeliveryState.DELIVERED:
                                app_delivered = True
                        elif ack.ack_kind == AckKind.HOP:
                            hop_ack = True
            else:
                send_accepted = bool(raw)

            if not send_accepted and not recipient_ack and not app_delivered:
                self.routes.report_route_failure(route.route_id, "mesh_send_failed")
                self.peer_health.record_failure(route.next_hop_id, "mesh_send_failed")
                rejected.append({"route_id": route.route_id, "reason": "mesh_send_failed"})
                last_error = "mesh_send_failed"
                continue

            self.routes.report_route_success(
                route.route_id, metrics={"latency_ms": latency_ms}
            )
            self.peer_health.record_success(route.next_hop_id, latency_ms)

            if app_delivered or recipient_ack:
                state = DeliveryState.DELIVERED
            elif hop_ack:
                state = DeliveryState.FORWARDED
            else:
                state = DeliveryState.ACCEPTED

            return DeliveryOutcome(
                state=state,
                message_id=envelope.message_id,
                route_id=route.route_id,
                transport="mesh",
                attempts=attempts,
                hop_acks=1 if hop_ack else 0,
                destination_ack=recipient_ack or app_delivered,
                selected_routes=selected,
                rejected_routes=rejected,
                latency_ms=latency_ms,
                details={
                    "destination": dest.to_dict(),
                    "node_id": dest.canonical_id,
                    "hop_limit": envelope.hop_limit,
                    "expires_at": envelope.expires_at,
                },
            )

        return DeliveryOutcome(
            state=DeliveryState.FAILED,
            message_id=envelope.message_id,
            attempts=attempts,
            failure_reason=last_error,
            selected_routes=selected,
            rejected_routes=rejected,
            details={
                "destination": dest.to_dict(),
                "node_id": dest.canonical_id,
                "result_kind": "failed" if attempts else "unreachable",
            },
        )

    def ingest_acknowledgment(self, ack_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process an inbound authenticated ACK. Rejects invalid signatures when secret set."""
        try:
            ack = Acknowledgment.from_dict(ack_data)
        except Exception as e:
            return {"ok": False, "error": f"malformed_ack:{e}"}
        secret = _mesh_secret()
        if secret and not ack.verify(secret):
            return {"ok": False, "error": "ack_signature_invalid"}
        if ack.ack_kind == AckKind.DESTINATION and ack.state == DeliveryState.DELIVERED:
            self.peer_health.record_success(ack.from_id, ack.latency_ms)
        return {
            "ok": True,
            "message_id": ack.message_id,
            "ack_kind": ack.ack_kind.value,
            "state": ack.state.value,
            "from_id": ack.from_id,
        }

    def create_destination_ack(
        self,
        message_id: str,
        destination_id: str,
        *,
        state: DeliveryState = DeliveryState.DELIVERED,
        latency_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build a signed destination-level acknowledgment (for tests / responders)."""
        ack = Acknowledgment(
            message_id=message_id,
            ack_kind=AckKind.DESTINATION,
            from_id=self._local_node_id,
            destination_id=destination_id,
            state=state,
            latency_ms=latency_ms,
        )
        secret = _mesh_secret()
        if secret:
            ack.sign(secret)
        return ack.to_dict()

    def _record_outcome(self, result: Dict[str, Any]) -> None:
        safe = {
            k: v
            for k, v in result.items()
            if k
            not in (
                "payload",
                "body",
                "data",
                "secret",
                "password",
                "token",
                "api_key",
            )
        }
        self._delivery_log.append(safe)
        if len(self._delivery_log) > self._max_delivery_log:
            self._delivery_log = self._delivery_log[-self._max_delivery_log :]

    def recent_deliveries(self) -> List[Dict[str, Any]]:
        """Recent delivery outcomes for diagnostics (no message contents)."""
        return list(self._delivery_log)

    def peer_health_snapshot(self) -> Dict[str, Any]:
        return self.peer_health.list_peers()

    def resolve_and_probe(self, target: str) -> Dict[str, Any]:
        """Resolve + connection probe (mesh ack or TCP/HTTPS handshake). Not delivery."""
        dest, err = self.resolver.try_resolve(target)
        if err or dest is None:
            return {
                "ok": False,
                "error": err or "unresolved",
                "target": target,
                "result_kind": "unreachable",
            }
        policy = RoutePolicy(allow_egress=False)
        result: ConnectionResult = self.connections.connect(
            dest, policy=policy, probe_only=True
        )
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
