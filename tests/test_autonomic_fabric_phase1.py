"""Aurora Autonomic Fabric Phase 1 — delivery states, health, recovery, ACKs, security.

Deterministic unit + simulated multi-node tests. Distinguishes simulated results
from real-device validation (these are simulated with controllable transport).
"""

from __future__ import annotations

import os
import time
import unittest
from typing import Any, Dict, List, Optional

from comms.routing.config import RoutingConfig
from comms.routing.delivery import (
    AckKind,
    Acknowledgment,
    DedupCache,
    DeliveryState,
    MessageEnvelope,
    PeerHealthTracker,
)
from comms.routing.service import DestinationRoutingService


class EnvelopeAndAckTests(unittest.TestCase):
    def test_envelope_message_id_and_expiry(self):
        env = MessageEnvelope(
            message_id="",
            destination_id="node-b",
            source_id="node-a",
            payload={"text": "hi"},
            expires_at=time.time() + 60,
        )
        self.assertTrue(env.message_id)
        self.assertFalse(env.is_expired)
        self.assertEqual(env.hops_remaining, 8)
        env.hop_count = 8
        self.assertFalse(env.can_forward())

    def test_envelope_sign_verify(self):
        secret = b"test-secret-key-32bytes-long!!!!"
        env = MessageEnvelope(
            message_id="mid1",
            destination_id="node-b",
            source_id="node-a",
            payload={},
        )
        env.sign(secret)
        self.assertTrue(env.verify(secret))
        env.hop_count = 1
        self.assertFalse(env.verify(secret))

    def test_ack_sign_verify_destination(self):
        secret = b"test-secret-key-32bytes-long!!!!"
        ack = Acknowledgment(
            message_id="mid1",
            ack_kind=AckKind.DESTINATION,
            from_id="node-b",
            destination_id="node-b",
            state=DeliveryState.DELIVERED,
        )
        ack.sign(secret)
        self.assertTrue(ack.verify(secret))
        bad = Acknowledgment.from_dict(ack.to_dict())
        bad.signature = "deadbeef" * 8
        self.assertFalse(bad.verify(secret))

    def test_dedup_rejects_replay(self):
        cache = DedupCache(max_entries=16, default_ttl=60)
        self.assertTrue(cache.check_and_record("m1", "n1"))
        self.assertFalse(cache.check_and_record("m1", "n1"))
        self.assertFalse(cache.check_and_record("m1", "n2"))
        self.assertEqual(cache.stats()["replays"], 2)


class PeerHealthTests(unittest.TestCase):
    def test_temporary_loss_vs_confirmed(self):
        t = PeerHealthTracker()
        t.record_failure("peer-x", "timeout")
        h = t.get("peer-x")
        self.assertTrue(h.is_temporarily_lost or h.consecutive_failures == 1)
        self.assertFalse(h.unreachable_confirmed)
        for _ in range(5):
            t.record_failure("peer-x", "timeout", confirm_unreachable=False)
        h = t.get("peer-x")
        self.assertTrue(h.unreachable_confirmed)
        t.record_success("peer-x", 12.0)
        h = t.get("peer-x")
        self.assertFalse(h.unreachable_confirmed)
        self.assertTrue(h.is_reachable)


class ControllableTransport:
    """Fault-injection harness for simulated two/three-node mesh."""

    def __init__(self):
        self.fail_nodes: set = set()
        self.delay_nodes: set = set()
        self.ack_mode: str = "accepted"
        self.calls: List[Dict[str, Any]] = []
        self.deliveries: Dict[str, List[Any]] = {}

    def send(self, node_id: str, body: Any) -> Any:
        self.calls.append({"node_id": node_id, "body": body})
        if node_id in self.fail_nodes:
            return False
        if node_id in self.delay_nodes:
            time.sleep(0.05)
        self.deliveries.setdefault(node_id, []).append(body)
        if self.ack_mode == "fail":
            return False
        if self.ack_mode == "destination":
            mid = ""
            if isinstance(body, dict):
                env = body.get("_aurora_envelope") or {}
                mid = env.get("message_id") or ""
            return {
                "ok": True,
                "send_accepted": True,
                "recipient_acknowledged": True,
                "application_delivered": True,
                "ack": {
                    "message_id": mid,
                    "ack_kind": "destination",
                    "from_id": node_id,
                    "destination_id": node_id,
                    "state": "DELIVERED",
                    "created_at": time.time(),
                    "nonce": "sim",
                    "signature": "",
                },
            }
        if self.ack_mode == "hop":
            return {"ok": True, "send_accepted": True, "hop_acknowledged": True}
        return True


class HealthyDirectDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.transport = ControllableTransport()
        nodes = {"node-a": {"online": True}, "node-b": {"online": True}}
        self.svc = DestinationRoutingService(
            config=RoutingConfig(enabled=True, route_max_retries=2),
            node_lookup=lambda n: nodes.get(n),
            mesh_send=self.transport.send,
            local_node_id="node-a",
        )

    def test_healthy_direct_delivery_accepted(self):
        r = self.svc.mesh_send_to("node-b", {"text": "ping"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["state"], "ACCEPTED")
        self.assertTrue(r["send_accepted"])
        self.assertFalse(r.get("recipient_acknowledged"))
        self.assertFalse(r.get("application_delivered"))
        self.assertTrue(r.get("message_id"))
        self.assertEqual(len(self.transport.calls), 1)

    def test_destination_ack_promotes_to_delivered(self):
        self.transport.ack_mode = "destination"
        r = self.svc.mesh_send_to("node-b", {"text": "ping"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["state"], "DELIVERED")
        self.assertTrue(r["recipient_acknowledged"])
        self.assertTrue(r["application_delivered"])

    def test_hop_ack_is_forwarded_not_delivered(self):
        self.transport.ack_mode = "hop"
        r = self.svc.mesh_send_to("node-b", {"text": "ping"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["state"], "FORWARDED")
        self.assertFalse(r.get("application_delivered"))


class FailureAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.transport = ControllableTransport()
        self.nodes = {"node-b": {"online": True}, "dashboard": {"online": True}}
        self.svc = DestinationRoutingService(
            config=RoutingConfig(enabled=True, route_max_retries=2),
            node_lookup=lambda n: self.nodes.get(n),
            mesh_send=self.transport.send,
            local_node_id="node-a",
        )

    def test_direct_failure_then_recovery(self):
        self.transport.fail_nodes.add("node-b")
        r1 = self.svc.mesh_send_to("node-b", {"text": "fail"})
        self.assertFalse(r1["ok"])
        self.assertEqual(r1["state"], "FAILED")
        self.transport.fail_nodes.clear()
        time.sleep(0.01)
        for rc in self.svc.routes.list_routes():
            rc.cooldown_until = 0.0
            rc.failure_count = 0
        self.svc.peer_health.clear()
        r2 = self.svc.mesh_send_to("node-b", {"text": "ok"})
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["state"], "ACCEPTED")

    def test_retry_exhaustion(self):
        self.transport.fail_nodes.add("node-b")
        r = self.svc.mesh_send_to("node-b", {"text": "x"})
        self.assertFalse(r["ok"])
        self.assertEqual(r["state"], "FAILED")
        self.assertGreaterEqual(r.get("attempts", 0), 1)

    def test_no_mesh_route_unreachable(self):
        svc = DestinationRoutingService(
            config=RoutingConfig(enabled=True),
            node_lookup=lambda n: None,
            mesh_send=self.transport.send,
        )
        r = svc.mesh_send_to("8.8.8.8", {})
        self.assertFalse(r["ok"])
        self.assertIn(r.get("result_kind"), ("unreachable", "failed"))


class SecurityBoundaryTests(unittest.TestCase):
    def test_duplicate_packet_rejected_locally(self):
        transport = ControllableTransport()
        nodes = {"node-b": {}}
        svc = DestinationRoutingService(
            config=RoutingConfig(enabled=True),
            node_lookup=lambda n: nodes.get(n),
            mesh_send=transport.send,
        )
        cache = svc.dedup
        self.assertTrue(cache.check_and_record("same-mid", "n1"))
        self.assertFalse(cache.check_and_record("same-mid", "n1"))

    def test_invalid_ack_signature_rejected(self):
        os.environ["AURORA_MESH_SECRET"] = "unit-test-secret-value"
        try:
            svc = DestinationRoutingService(
                config=RoutingConfig(enabled=True),
                local_node_id="node-a",
            )
            bad_ack = {
                "message_id": "m1",
                "ack_kind": "destination",
                "from_id": "evil",
                "destination_id": "node-b",
                "state": "DELIVERED",
                "created_at": time.time(),
                "nonce": "x",
                "signature": "00" * 32,
            }
            r = svc.ingest_acknowledgment(bad_ack)
            self.assertFalse(r["ok"])
            self.assertIn("signature", r.get("error", ""))
        finally:
            os.environ.pop("AURORA_MESH_SECRET", None)

    def test_valid_ack_accepted_when_signed(self):
        os.environ["AURORA_MESH_SECRET"] = "unit-test-secret-value"
        try:
            svc = DestinationRoutingService(
                config=RoutingConfig(enabled=True),
                local_node_id="node-b",
            )
            ack = svc.create_destination_ack("m99", "node-b")
            r = svc.ingest_acknowledgment(ack)
            self.assertTrue(r["ok"])
            self.assertEqual(r["message_id"], "m99")
        finally:
            os.environ.pop("AURORA_MESH_SECRET", None)

    def test_malicious_route_not_manipulable_via_unauth_peer(self):
        transport = ControllableTransport()
        svc = DestinationRoutingService(
            config=RoutingConfig(enabled=True),
            node_lookup=lambda n: {"node-b": {}}[n] if n == "node-b" else None,
            mesh_send=transport.send,
        )
        from comms.routing.gateway import GatewayAdvertisement

        fake = GatewayAdvertisement(
            gateway_id="evil-gw",
            node_id="evil",
            supported_transports=["mesh", "tcp"],
            sequence=1,
            expires_at=time.time() + 600,
            auth="none",
            signature="",
        )
        svc.gateways.ingest(fake.to_dict())
        r = svc.mesh_send_to("node-b", {})
        self.assertTrue(r["ok"])
        self.assertIn("mesh:node-b", r.get("route_id") or "")


class NoInternetNoGatewayTests(unittest.TestCase):
    def test_local_mesh_without_egress(self):
        transport = ControllableTransport()
        svc = DestinationRoutingService(
            config=RoutingConfig(
                enabled=True,
                egress_gateway_enabled=False,
            ),
            node_lookup=lambda n: {"node-b": {}} if n == "node-b" else None,
            mesh_send=transport.send,
        )
        r = svc.mesh_send_to("node-b", {"offline": True})
        self.assertTrue(r["ok"])
        self.assertFalse(svc.config.egress_gateway_enabled)
        status = svc.diagnostics.network_status()
        self.assertTrue(status["routing_enabled"])

    def test_hostname_egress_not_via_mesh_send(self):
        transport = ControllableTransport()
        svc = DestinationRoutingService(
            config=RoutingConfig(enabled=True, egress_gateway_enabled=False),
            mesh_send=transport.send,
        )
        r = svc.mesh_send_to("example.com", {})
        self.assertFalse(r["ok"])


class DiagnosticsRedactionTests(unittest.TestCase):
    def test_delivery_log_has_no_payload(self):
        transport = ControllableTransport()
        svc = DestinationRoutingService(
            config=RoutingConfig(enabled=True),
            node_lookup=lambda n: {"node-b": {}} if n == "node-b" else None,
            mesh_send=transport.send,
        )
        svc.mesh_send_to("node-b", {"secret_token": "SHOULD_NOT_APPEAR", "text": "hi"})
        for entry in svc.recent_deliveries():
            blob = str(entry)
            self.assertNotIn("SHOULD_NOT_APPEAR", blob)
            self.assertNotIn("secret_token", blob)


class TwoNodeThreeNodeSimTests(unittest.TestCase):
    """Simulated two-node and three-node delivery before/after link failure.

    These are *simulated* with ControllableTransport, not real-device validation.
    """

    def test_two_node_before_and_after_failure(self):
        transport = ControllableTransport()
        nodes = {"node-b": {"online": True}}
        svc = DestinationRoutingService(
            config=RoutingConfig(enabled=True, route_max_retries=1),
            node_lookup=lambda n: nodes.get(n),
            mesh_send=transport.send,
            local_node_id="node-a",
        )
        r1 = svc.mesh_send_to("node-b", {"phase": "before"})
        self.assertTrue(r1["ok"])
        self.assertEqual(r1["state"], "ACCEPTED")

        transport.fail_nodes.add("node-b")
        for rc in svc.routes.list_routes():
            rc.cooldown_until = 0.0
        r2 = svc.mesh_send_to("node-b", {"phase": "during"})
        self.assertFalse(r2["ok"])
        self.assertEqual(r2["state"], "FAILED")

        transport.fail_nodes.clear()
        for rc in svc.routes.list_routes():
            rc.cooldown_until = 0.0
            rc.failure_count = 0
        svc.peer_health.clear()
        transport.ack_mode = "destination"
        r3 = svc.mesh_send_to("node-b", {"phase": "after"})
        self.assertTrue(r3["ok"])
        self.assertEqual(r3["state"], "DELIVERED")
        self.assertTrue(r3.get("destination_ack") or r3.get("recipient_acknowledged"))

    def test_three_node_peer_health_tracking(self):
        transport = ControllableTransport()
        nodes = {"node-b": {}, "node-c": {}}
        svc = DestinationRoutingService(
            config=RoutingConfig(enabled=True),
            node_lookup=lambda n: nodes.get(n),
            mesh_send=transport.send,
            local_node_id="node-a",
        )
        svc.mesh_send_to("node-b", {})
        svc.mesh_send_to("node-c", {})
        health = svc.peer_health_snapshot()
        self.assertIn("node-b", health)
        self.assertIn("node-c", health)
        self.assertTrue(health["node-b"]["is_reachable"])


class APICompatibilityTests(unittest.TestCase):
    def test_legacy_result_kind_fields_present(self):
        transport = ControllableTransport()
        svc = DestinationRoutingService(
            config=RoutingConfig(enabled=True),
            node_lookup=lambda n: {"node-b": {}} if n == "node-b" else None,
            mesh_send=transport.send,
        )
        r = svc.mesh_send_to("node-b", {})
        for key in (
            "ok",
            "result_kind",
            "send_accepted",
            "recipient_acknowledged",
            "application_delivered",
            "state",
            "message_id",
        ):
            self.assertIn(key, r)


if __name__ == "__main__":
    unittest.main()
