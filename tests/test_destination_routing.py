#!/usr/bin/env python3
"""Tests for Aurora Destination Discovery & Gateway Routing v0.1 security gate."""
from __future__ import annotations
import os, sys, time, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comms.routing.config import RoutingConfig, load_routing_config
from comms.routing.connection import ConnectionManager
from comms.routing.destination import Destination, DestinationError, DestinationKind, DestinationResolver
from comms.routing.egress import EgressConfig, EgressGateway, RELAY_IMPLEMENTED
from comms.routing.gateway import GatewayAdvertisement, GatewayRegistry
from comms.routing.policy import address_allowed, is_blocked_address, validate_resolved_for_egress, validate_selected_address
from comms.routing.route import RouteCandidate, RouteManager, RoutePolicy
from comms.routing.service import DestinationRoutingService

class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.r = DestinationResolver(
            known_services={"comms": {"transport": "mesh"}, "mining": {}},
            node_lookup=lambda n: {"node_id": n} if n == "worker-01" else None,
            dns_resolver=lambda h, t: (["93.184.216.34"], 60.0))
    def test_ipv4_literal(self):
        self.assertEqual(self.r.classify("8.8.8.8"), DestinationKind.IPV4)
    def test_ipv4_with_port(self):
        d = self.r.resolve("8.8.8.8:443")
        self.assertEqual(d.kind, DestinationKind.IPV4); self.assertEqual(d.port, 443)
    def test_ipv6_literal(self):
        self.assertEqual(self.r.classify("2001:db8::1"), DestinationKind.IPV6)
    def test_bracketed_ipv6(self):
        self.assertEqual(self.r.classify("[2001:db8::1]"), DestinationKind.IPV6)
    def test_bracketed_ipv6_with_port(self):
        d = self.r.resolve("[2001:db8::1]:443")
        self.assertEqual(d.kind, DestinationKind.IPV6); self.assertEqual(d.port, 443)
    def test_localhost_is_hostname(self):
        self.assertEqual(self.r.classify("localhost"), DestinationKind.HOSTNAME)
    def test_hostname(self):
        self.assertEqual(self.r.classify("example.com"), DestinationKind.HOSTNAME)
    def test_url_hostname(self):
        self.assertEqual(self.r.classify("https://example.com/path"), DestinationKind.HOSTNAME)
    def test_url_with_port(self):
        d = self.r.resolve("https://example.com:8443/x")
        self.assertEqual(d.kind, DestinationKind.HOSTNAME); self.assertEqual(d.port, 8443)
    def test_service_known(self):
        self.assertEqual(self.r.classify("comms"), DestinationKind.SERVICE)
    def test_node_via_lookup(self):
        self.assertEqual(self.r.classify("worker-01"), DestinationKind.NODE)
    def test_content_sha256(self):
        self.assertEqual(self.r.classify("sha256:" + "ab" * 32), DestinationKind.CONTENT)
    def test_ip_not_service(self):
        self.assertEqual(self.r.classify("8.8.8.8"), DestinationKind.IPV4)
    def test_malformed_hostname_rejected(self):
        with self.assertRaises(DestinationError): self.r.classify("bad host!")
    def test_empty_rejected(self):
        with self.assertRaises(DestinationError): self.r.classify("")
    def test_malformed_ipv6_rejected(self):
        with self.assertRaises(DestinationError): self.r.classify("[not-an-ip]")
    def test_ambiguous_rejected(self):
        with self.assertRaises(DestinationError): self.r.classify("!!!")
    def test_cache_hit(self):
        self.r.resolve("example.com"); self.r.resolve("example.com")
        self.assertGreaterEqual(self.r.stats()["cache_hit"], 1)
    def test_dns_failure(self):
        r = DestinationResolver(dns_resolver=lambda h, t: (_ for _ in ()).throw(DestinationError("dns_failed:test")))
        dest, err = r.try_resolve("no-such.example")
        self.assertIsNone(dest); self.assertIn("dns", (err or "").lower())

class PolicyTests(unittest.TestCase):
    def test_loopback_blocked(self): self.assertTrue(is_blocked_address("127.0.0.1"))
    def test_private_blocked(self):
        self.assertTrue(is_blocked_address("192.168.1.1"))
        self.assertTrue(is_blocked_address("10.0.0.1"))
        self.assertTrue(is_blocked_address("172.16.0.1"))
    def test_link_local_blocked(self): self.assertTrue(is_blocked_address("169.254.1.1"))
    def test_cgnat_blocked(self): self.assertTrue(is_blocked_address("100.64.0.1"))
    def test_public_ok(self): self.assertFalse(is_blocked_address("8.8.8.8"))
    def test_ipv6_loopback(self): self.assertTrue(is_blocked_address("::1"))
    def test_ipv6_ula(self): self.assertTrue(is_blocked_address("fd12:3456::1"))
    def test_ipv4_mapped_ipv6_blocked(self):
        self.assertTrue(is_blocked_address("::ffff:127.0.0.1"))
        self.assertTrue(is_blocked_address("::ffff:192.168.1.1"))
        ok, _ = address_allowed("::ffff:10.0.0.1", deny_private=True)
        self.assertFalse(ok)
    def test_documentation_ipv6(self): self.assertTrue(is_blocked_address("2001:db8::1"))
    def test_dns_rebinding_blocked(self):
        ok, reason = validate_resolved_for_egress(["127.0.0.1"], 80, deny_private=True)
        self.assertFalse(ok); self.assertIn("blocked", reason)
    def test_egress_deny_private_always(self):
        ok, _ = validate_resolved_for_egress(["10.0.0.5"], 443, deny_private=True)
        self.assertFalse(ok)
    def test_egress_allow_public(self):
        ok, _ = validate_resolved_for_egress(["8.8.8.8"], 443, deny_private=True)
        self.assertTrue(ok)
    def test_selected_address_check(self):
        ok, _ = validate_selected_address("8.8.8.8", 443, deny_private=True)
        self.assertTrue(ok)
        ok, _ = validate_selected_address("127.0.0.1", 443, deny_private=True)
        self.assertFalse(ok)

class GatewayRegistryTests(unittest.TestCase):
    def setUp(self):
        os.environ["AURORA_MESH_SECRET"] = "test-secret-xyz"
        self.reg = GatewayRegistry()
    def tearDown(self):
        os.environ.pop("AURORA_MESH_SECRET", None)
    def _ad(self, seq=1, expires_delta=60, **kw):
        now = time.time()
        adv = GatewayAdvertisement(node_id="n1", gateway_id="gw1", sequence=seq,
            issued_at=now, expires_at=now + expires_delta, supported_transports=["mesh"], **kw)
        return adv.sign("test-secret-xyz")
    def test_valid_ad_accepted(self):
        ok, reason, _ = self.reg.ingest(self._ad().to_dict(), secret="test-secret-xyz")
        self.assertTrue(ok, reason)
    def test_bad_signature_rejected(self):
        d = self._ad().to_dict(); d["signature"] = "00" * 32
        ok, reason, _ = self.reg.ingest(d, secret="test-secret-xyz")
        self.assertFalse(ok); self.assertEqual(reason, "bad_signature")
    def test_expired_rejected(self):
        ok, reason, _ = self.reg.ingest(self._ad(expires_delta=-10).to_dict(), secret="test-secret-xyz")
        self.assertFalse(ok); self.assertEqual(reason, "expired")
    def test_replay_same_seq_rejected(self):
        self.reg.ingest(self._ad(seq=5).to_dict(), secret="test-secret-xyz")
        ok, reason, _ = self.reg.ingest(self._ad(seq=5).to_dict(), secret="test-secret-xyz")
        self.assertFalse(ok); self.assertEqual(reason, "stale_sequence")
    def test_stale_sequence_rejected(self):
        self.reg.ingest(self._ad(seq=10).to_dict(), secret="test-secret-xyz")
        ok, reason, _ = self.reg.ingest(self._ad(seq=3).to_dict(), secret="test-secret-xyz")
        self.assertFalse(ok)

class RouteManagerTests(unittest.TestCase):
    def setUp(self):
        os.environ["AURORA_MESH_SECRET"] = "test-secret-xyz"
        self.reg = GatewayRegistry()
        self.rm = RouteManager(gateway_registry=self.reg,
            node_lookup=lambda n: {"node_id": n} if n == "worker-01" else None, hysteresis_hold=0.0)
    def tearDown(self):
        os.environ.pop("AURORA_MESH_SECRET", None)
    def test_mesh_route_for_node(self):
        dest = Destination(kind=DestinationKind.NODE, canonical_id="worker-01")
        routes = self.rm.discover_routes(dest)
        self.assertTrue(any(r.transport == "mesh" for r in routes))
    def test_unauthorized_gateway_not_selected(self):
        now = time.time()
        adv = GatewayAdvertisement(node_id="evil", gateway_id="evil-gw", sequence=1,
            issued_at=now, expires_at=now + 60, auth="none", signature="", supported_transports=["tcp"])
        self.reg._by_id[adv.gateway_id] = adv
        dest = Destination(kind=DestinationKind.HOSTNAME, canonical_id="example.com",
            hostname="example.com", resolved_addresses=["93.184.216.34"])
        selected = self.rm.select_route(dest, RoutePolicy(require_auth=True))
        if selected and selected.next_hop_id == "evil-gw":
            self.fail("unauthorized gateway was selected")
    def test_failure_then_alternate(self):
        dest = Destination(kind=DestinationKind.NODE, canonical_id="worker-01")
        self.rm.discover_routes(dest)
        r1 = self.rm.select_route(dest)
        self.assertIsNotNone(r1)
        self.rm.report_route_failure(r1.route_id, "timeout")
        self.assertTrue(self.rm._routes[r1.route_id].in_cooldown)
    def test_invalidate(self):
        dest = Destination(kind=DestinationKind.NODE, canonical_id="worker-01")
        self.rm.discover_routes(dest)
        r1 = self.rm.select_route(dest)
        rid = r1.route_id
        self.rm.invalidate_route(rid, "test")
        self.assertNotIn(rid, self.rm._routes)

class ConnectionPolicyTests(unittest.TestCase):
    def test_policy_blocks_private_on_tcp(self):
        cfg = RoutingConfig(deny_private_for_egress=True, route_max_retries=0)
        rm = RouteManager(hysteresis_hold=0.0)
        cm = ConnectionManager(route_manager=rm, config=cfg)
        dest = Destination(kind=DestinationKind.HOSTNAME, canonical_id="internal.local",
            hostname="internal.local", resolved_addresses=["192.168.1.50"], port=80)
        now = time.time()
        rc = RouteCandidate(route_id="direct:internal:80", destination_key="hostname:internal.local",
            next_hop_id="local", transport="tcp", endpoint="192.168.1.50:80",
            trust_ok=True, authorized=True, expires_at=now + 60,
            metadata={"addresses": ["192.168.1.50"]})
        rm._store(rc)
        result = cm.connect(dest, policy=RoutePolicy(allow_egress=True, require_auth=False))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_category, "policy")
    def test_mesh_ack_kind(self):
        cfg = RoutingConfig(route_max_retries=0)
        rm = RouteManager(node_lookup=lambda n: {"node_id": n}, hysteresis_hold=0.0)
        cm = ConnectionManager(route_manager=rm, config=cfg, mesh_send=lambda nid, payload: True)
        dest = Destination(kind=DestinationKind.NODE, canonical_id="worker-01")
        result = cm.connect(dest, policy=RoutePolicy(require_auth=False), probe_only=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.result_kind, "probe")
        self.assertEqual(result.transport, "mesh")

class EgressGatewayTests(unittest.TestCase):
    def test_disabled_by_default(self):
        gw = EgressGateway()
        self.assertFalse(gw.config.enabled)
        ok, reason = gw.authorize_request("n1", ["8.8.8.8"], 443)
        self.assertFalse(ok); self.assertEqual(reason, "egress_disabled")
    def test_relay_not_implemented(self):
        self.assertFalse(RELAY_IMPLEMENTED)
        gw = EgressGateway(EgressConfig(enabled=True, port=9999, bind_host="127.0.0.1"))
        self.assertFalse(gw.start_listener())
        self.assertFalse(gw.listen_ok)
        self.assertEqual(gw.last_error, "relay_not_implemented")
    def test_deny_private_even_when_enabled(self):
        gw = EgressGateway(EgressConfig(enabled=True, deny_private=True, port=0))
        ok, _ = gw.authorize_request("n1", ["10.0.0.1"], 443)
        self.assertFalse(ok)
    def test_port_allowlist(self):
        gw = EgressGateway(EgressConfig(enabled=True, deny_private=True, allowed_ports={443}))
        ok, reason = gw.authorize_request("n1", ["8.8.8.8"], 80)
        self.assertFalse(ok); self.assertEqual(reason, "port_denied")
    def test_status_shape(self):
        st = EgressGateway().status()
        self.assertIn("enabled", st); self.assertIn("relay_implemented", st)
        self.assertFalse(st["relay_implemented"])

class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.svc = DestinationRoutingService(config=RoutingConfig(enabled=False),
            node_lookup=lambda n: {"node_id": n} if n == "worker-01" else None)
    def test_unresolved(self):
        out = self.svc.diagnostics.resolve_target("!!!")
        self.assertFalse(out["ok"]); self.assertEqual(out["reachable_hint"], "unresolved")
    def test_resolve_node(self):
        out = self.svc.diagnostics.resolve_target("worker-01")
        self.assertTrue(out["ok"]); self.assertTrue(out["resolved"])
    def test_network_status(self):
        st = self.svc.diagnostics.network_status()
        self.assertTrue(st["ok"]); self.assertFalse(st["egress"]["relay_implemented"])
    def test_list_gateways_empty(self):
        out = self.svc.diagnostics.list_gateways()
        self.assertTrue(out["ok"]); self.assertEqual(out["count"], 0)

class ConfigTests(unittest.TestCase):
    def test_defaults_disabled(self):
        cfg = load_routing_config()
        self.assertFalse(cfg.enabled); self.assertFalse(cfg.egress_gateway_enabled)
    def test_validate_bad_ttl(self):
        cfg = RoutingConfig(route_ttl=0)
        self.assertTrue(any("TTL" in p for p in cfg.validate()))

class ServiceFacadeTests(unittest.TestCase):
    def test_init_disabled(self):
        svc = DestinationRoutingService(config=RoutingConfig(enabled=False))
        self.assertFalse(svc.config.enabled)
    def test_start_stop_noop_when_disabled(self):
        svc = DestinationRoutingService(config=RoutingConfig(enabled=False))
        svc.start(); svc.stop()

class GracefulDegradationTests(unittest.TestCase):
    def test_no_public_prerequisite(self):
        svc = DestinationRoutingService(config=RoutingConfig(enabled=True),
            node_lookup=lambda n: {"node_id": n} if n == "n1" else None,
            mesh_send=lambda a, b: True)
        dest = Destination(kind=DestinationKind.NODE, canonical_id="n1")
        routes = svc.routes.discover_routes(dest)
        self.assertTrue(any(r.transport == "mesh" for r in routes))
    def test_resolver_without_dns(self):
        r = DestinationResolver()
        d = r.resolve("example.com", allow_dns=False)
        self.assertEqual(d.resolution_source, "hostname_unresolved")
        self.assertEqual(d.resolved_addresses, [])

class DashboardEndpointTests(unittest.TestCase):
    def test_resolve_endpoint_shape(self):
        svc = DestinationRoutingService(config=RoutingConfig(enabled=False),
            node_lookup=lambda n: {"node_id": n} if n == "worker-01" else None)
        out = svc.diagnostics.resolve_target("worker-01")
        for key in ("ok", "target", "resolved", "reachable_hint", "candidate_count"):
            self.assertIn(key, out)
    def test_routes_endpoint_shape(self):
        out = DestinationRoutingService(config=RoutingConfig(enabled=False)).diagnostics.list_routes()
        self.assertIn("routes", out); self.assertIn("count", out)
    def test_gateways_endpoint_shape(self):
        out = DestinationRoutingService(config=RoutingConfig(enabled=False)).diagnostics.list_gateways()
        self.assertIn("gateways", out)
    def test_network_status_endpoint_shape(self):
        out = DestinationRoutingService(config=RoutingConfig(enabled=False)).diagnostics.network_status()
        self.assertIn("routing_enabled", out); self.assertIn("egress", out)

class MeshRegressionTests(unittest.TestCase):
    def test_beacon_auth_still_works(self):
        from comms.beacon_auth import sign_beacon, verify_beacon
        os.environ["AURORA_MESH_SECRET"] = "lan-test-secret"
        try:
            body = {"magic": "AURORA_MESH_V1", "node_id": "node-b",
                    "redis_url": "redis://192.168.1.20:6379/0", "ts": 1,
                    "fingerprint": "abc", "role": "peer"}
            signed = sign_beacon(body)
            ok, reason = verify_beacon(signed)
            self.assertTrue(ok, reason)
        finally:
            os.environ.pop("AURORA_MESH_SECRET", None)

if __name__ == "__main__":
    unittest.main()
