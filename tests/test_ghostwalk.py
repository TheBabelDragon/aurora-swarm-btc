"""Ghostwalk Phase 2 — deterministic unit + simulated multi-node tests."""

from __future__ import annotations

import time
import unittest

from mods.evidence_integrity import EvidenceStore

from comms.ghostwalk.anomalies import AnomalyEngine, FindingStatus
from comms.ghostwalk.identity import AuthResult, TrustDecision, TrustPolicy, TrustPolicyEngine
from comms.ghostwalk.recovery import ProposalStatus, RecoveryEngine
from comms.ghostwalk.service import GhostwalkService
from comms.ghostwalk.topology import ObservationKind, ObservationSource, TopologyEngine


class IdentityTrustTests(unittest.TestCase):
    def test_auth_does_not_equal_trust_elevation_from_capabilities(self):
        eng = TrustPolicyEngine(TrustPolicy(require_auth=False, allow_unsigned=True))
        rec = eng.evaluate(
            "node-b",
            fingerprint="abc",
            auth_result=AuthResult.UNSIGNED,
            capabilities=["admin", "egress", "root"],
        )
        self.assertEqual(rec.trust_decision, TrustDecision.DEFER)
        self.assertNotEqual(rec.identity_state.value, "authenticated")

    def test_secret_ok_allows(self):
        eng = TrustPolicyEngine()
        rec = eng.evaluate("node-b", fingerprint="fp1", auth_result=AuthResult.SECRET_OK)
        self.assertEqual(rec.trust_decision, TrustDecision.ALLOW)
        self.assertEqual(rec.auth_result, AuthResult.SECRET_OK)

    def test_fingerprint_mismatch_quarantines(self):
        eng = TrustPolicyEngine()
        eng.evaluate("node-b", fingerprint="fp1", auth_result=AuthResult.SECRET_OK)
        rec = eng.evaluate("node-b", fingerprint="fp2", auth_result=AuthResult.SECRET_OK)
        self.assertEqual(rec.trust_decision, TrustDecision.QUARANTINE)
        self.assertEqual(rec.identity_state.value, "conflict")

    def test_malformed_raises(self):
        eng = TrustPolicyEngine()
        with self.assertRaises(ValueError):
            eng.evaluate("", auth_result=AuthResult.NONE)

    def test_require_auth_denies_unsigned(self):
        eng = TrustPolicyEngine(TrustPolicy(require_auth=True, allow_unsigned=False))
        rec = eng.evaluate("node-b", auth_result=AuthResult.UNSIGNED)
        self.assertEqual(rec.trust_decision, TrustDecision.DENY)

    def test_revoke_preserves_evidence_refs(self):
        eng = TrustPolicyEngine()
        eng.evaluate("node-b", fingerprint="fp", auth_result=AuthResult.SECRET_OK, evidence_ref="e1")
        rec = eng.revoke("node-b", "operator", evidence_ref="e2")
        self.assertTrue(rec.revoked)
        self.assertIn("e1", rec.evidence_refs)
        self.assertIn("e2", rec.evidence_refs)

    def test_unavailable_not_malicious_by_default(self):
        # Stale is an anomaly elsewhere; trust engine does not auto-malice
        eng = TrustPolicyEngine()
        rec = eng.evaluate("node-b", auth_result=AuthResult.UNSIGNED)
        self.assertEqual(rec.trust_decision, TrustDecision.DEFER)


class TopologyTests(unittest.TestCase):
    def test_direct_vs_advertised_source(self):
        t = TopologyEngine(local_node_id="a", clock=lambda: 1000.0)
        t.ingest(ObservationKind.PEER_SEEN, "b", source=ObservationSource.DIRECT)
        t.ingest(
            ObservationKind.PEER_SEEN,
            "c",
            source=ObservationSource.PEER_ADVERTISED,
            observer_id="b",
        )
        snap = t.snapshot()
        self.assertIn("b", snap.nodes)
        self.assertIn("c", snap.nodes)
        self.assertEqual(snap.nodes["c"]["source"], "peer_advertised")

    def test_stale_expiry(self):
        now = [1000.0]

        def clock():
            return now[0]

        t = TopologyEngine(local_node_id="a", default_ttl_s=10.0, clock=clock)
        t.ingest(ObservationKind.PEER_SEEN, "b")
        now[0] = 1020.0
        latest = t.latest_for("b")
        self.assertTrue(latest.is_stale(now[0]))

    def test_duplicate_bounded(self):
        t = TopologyEngine(local_node_id="a", max_timeline=20)
        for _ in range(50):
            t.ingest(ObservationKind.PEER_SEEN, "b")
        self.assertLessEqual(len(t.timeline(100)), 20)


class AnomalyTests(unittest.TestCase):
    def test_no_duplicate_open_findings(self):
        eng = AnomalyEngine()
        f1 = eng.note_peer_stale("b", last_seen=1.0, now=10.0)
        f2 = eng.note_peer_stale("b", last_seen=1.0, now=20.0)
        self.assertEqual(f1.finding_id, f2.finding_id)
        open_f = eng.list_findings(open_only=True)
        self.assertEqual(len([x for x in open_f if x["subject_id"] == "b"]), 1)

    def test_not_attack_claim(self):
        eng = AnomalyEngine()
        f = eng.note_auth_failure("b", reason="bad_secret")
        self.assertFalse(f.to_dict()["is_attack_claim"])
        self.assertTrue(f.alternatives)

    def test_delivery_threshold(self):
        eng = AnomalyEngine(delivery_fail_threshold=3)
        self.assertIsNone(eng.note_delivery_failures("b", count=2))
        f = eng.note_delivery_failures("b", count=3)
        self.assertIsNotNone(f)

    def test_resolve(self):
        eng = AnomalyEngine()
        f = eng.note_peer_stale("b", last_seen=1.0)
        eng.resolve(f.finding_id, reason="peer returned")
        self.assertEqual(eng.list_findings(open_only=True), [])


class EvidenceTests(unittest.TestCase):
    def test_persist_with_store(self):
        store = EvidenceStore()
        svc = GhostwalkService(local_node_id="a", evidence_store=store)
        out = svc.observe_peer_advertisement(
            "b", fingerprint="fp", auth_ok=True, auth_reason="secret", capabilities=["mesh"]
        )
        self.assertTrue(out["ok"])
        self.assertTrue(out["evidence"]["persisted"])
        self.assertEqual(out["evidence"]["persistence_status"], "durable")
        self.assertGreater(len(store), 0)

    def test_memory_only_without_store(self):
        svc = GhostwalkService(local_node_id="a")
        out = svc.observe_peer_advertisement("b", auth_ok=False, auth_reason="unsigned")
        self.assertIn("memory_only", out["evidence"]["persistence_status"])

    def test_no_secrets_in_receipt(self):
        svc = GhostwalkService(local_node_id="a")
        out = svc.observe_peer_advertisement("b", auth_reason="unsigned")
        blob = str(out["evidence"])
        self.assertNotIn("AURORA_MESH_SECRET", blob)


class RecoveryTests(unittest.TestCase):
    def test_proposal_not_executed(self):
        eng = RecoveryEngine(local_node_id="a")
        p = eng.propose("quarantine_peer", "b", trigger_evidence=["e1"])
        self.assertEqual(p.status, ProposalStatus.PROPOSED)
        self.assertFalse(p.to_dict()["is_executed"])

    def test_unauthorized_quarantine_attempt_rejected(self):
        eng = RecoveryEngine(local_node_id="a")
        p = eng.propose("quarantine_peer", "a")  # self
        self.assertEqual(p.authorization_required, "local_operator_only")


class MultiNodeSimTests(unittest.TestCase):
    """Three logical nodes: failure, diagnosis, recovery proposal."""

    def test_partition_and_recovery(self):
        store = EvidenceStore()
        a = GhostwalkService(local_node_id="node-a", evidence_store=store)
        # healthy mesh
        a.observe_peer_advertisement("node-b", fingerprint="fpb", auth_ok=True, auth_reason="secret")
        a.observe_peer_advertisement("node-c", fingerprint="fpc", auth_ok=True, auth_reason="secret")
        st = a.status()
        self.assertGreaterEqual(st["peer_counts"]["authenticated"], 2)

        # failure
        lost = a.observe_peer_lost("node-b", last_seen=time.time() - 120)
        self.assertEqual(lost["finding"]["rule_id"], "peer_stale")
        self.assertEqual(lost["proposal"]["action"], "mark_degraded")
        self.assertFalse(lost["proposal"]["is_executed"])

        # recovery observation
        back = a.observe_peer_advertisement(
            "node-b", fingerprint="fpb", auth_ok=True, auth_reason="secret"
        )
        self.assertTrue(back["ok"])
        a.anomalies.resolve(lost["finding"]["finding_id"], reason="peer returned")
        self.assertEqual(
            [f for f in a.anomalies.list_findings(open_only=True) if f["subject_id"] == "node-b"],
            [],
        )

    def test_status_legible(self):
        svc = GhostwalkService(local_node_id="solo")
        st = svc.status()
        self.assertTrue(st["ok"])
        self.assertIn("topology", st)
        self.assertIn("peer_counts", st)
        self.assertEqual(st["topology"]["observer_id"], "solo")


if __name__ == "__main__":
    unittest.main()
