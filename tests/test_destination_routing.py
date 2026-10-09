#!/usr/bin/env python3
"""Smoke tests for destination routing v0.1."""
from __future__ import annotations
import os, sys, time, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from comms.routing.destination import DestinationKind, DestinationResolver, DestinationError
from comms.routing.policy import is_blocked_address, validate_resolved_for_egress
from comms.routing.gateway import GatewayAdvertisement, GatewayRegistry
from comms.routing.route import RouteManager
from comms.routing.egress import EgressConfig, EgressGateway
from comms.routing.config import RoutingConfig, load_routing_config
from comms.routing.service import DestinationRoutingService

class T(unittest.TestCase):
    def test_classify(self):
        r = DestinationResolver(known_services={"comms": {}}, node_lookup=lambda n: {"w": {}} .get(n) if n=="w" else None, dns_resolver=lambda h: [])
        self.assertEqual(r.resolve("comms").kind, DestinationKind.SERVICE)
        self.assertEqual(r.resolve("w").kind, DestinationKind.NODE)
        self.assertEqual(r.resolve("1.2.3.4").kind, DestinationKind.IPV4)
        self.assertIn(r.resolve("localhost", allow_dns=False).kind, (DestinationKind.HOSTNAME, DestinationKind.SERVICE))
        self.assertEqual(r.resolve("sha256:"+"a"*64).kind, DestinationKind.CONTENT)
        with self.assertRaises(DestinationError):
            r.resolve("bad host!")
    def test_policy(self):
        self.assertTrue(is_blocked_address("127.0.0.1"))
        self.assertFalse(is_blocked_address("8.8.8.8"))
        ok, _ = validate_resolved_for_egress(["10.0.0.1"], 443, deny_private=True)
        self.assertFalse(ok)
        ok, _ = validate_resolved_for_egress(["8.8.8.8"], 443, deny_private=True)
        self.assertTrue(ok)
    def test_gateway(self):
        os.environ["AURORA_MESH_SECRET"] = "s"; os.environ["AURORA_MESH_REQUIRE_AUTH"] = "1"
        reg = GatewayRegistry(); now = time.time()
        adv = GatewayAdvertisement(node_id="n", gateway_id="g", sequence=1, issued_at=now, expires_at=now+60).sign()
        ok, reason, _ = reg.ingest(adv.to_dict())
        self.assertTrue(ok, reason)
        bad = adv.to_dict(); bad["signature"] = "00"*32
        ok, reason, _ = reg.ingest(bad)
        self.assertFalse(ok)
        os.environ.pop("AURORA_MESH_SECRET", None); os.environ.pop("AURORA_MESH_REQUIRE_AUTH", None)
    def test_route_failover(self):
        nodes = {"w": {"node_id": "w"}}
        rm = RouteManager(node_lookup=lambda n: nodes.get(n), hysteresis_hold=0.5)
        r = DestinationResolver(node_lookup=lambda n: nodes.get(n), dns_resolver=lambda h: [])
        dest = r.resolve("w")
        sel = rm.select_route(dest)
        self.assertIsNotNone(sel)
        rm.report_route_failure(sel.route_id, "x")
        cooled = [x for x in rm.list_routes(dest) if x.route_id == sel.route_id]
        self.assertTrue(cooled and cooled[0].in_cooldown)
    def test_egress_off(self):
        eg = EgressGateway(EgressConfig(enabled=False))
        ok, reason, _ = eg.open_outbound("n", "8.8.8.8", 443)
        self.assertFalse(ok)
        self.assertEqual(reason, "egress_disabled")
    def test_config_defaults(self):
        cfg = load_routing_config()
        self.assertFalse(cfg.enabled)
    def test_diagnostics(self):
        svc = DestinationRoutingService(config=RoutingConfig(enabled=True), node_lookup=lambda n: {"w":{"node_id":"w"}}.get(n), mesh_send=lambda a,b: True)
        out = svc.diagnostics.resolve_target("w")
        self.assertTrue(out["ok"])
        st = svc.diagnostics.network_status()
        self.assertIn("routing_enabled", st)

if __name__ == "__main__":
    unittest.main()
