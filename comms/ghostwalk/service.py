"""GhostwalkService — facade wiring identity, topology, anomalies, evidence, recovery."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

from .anomalies import AnomalyEngine, RULE_VERSION
from .evidence import EvidenceRecorder
from .identity import AuthResult, TrustDecision, TrustPolicy, TrustPolicyEngine
from .recovery import RecoveryEngine
from .topology import ObservationKind, ObservationSource, TopologyEngine

logger = logging.getLogger("aurora.comms.ghostwalk")


def _map_auth_reason(reason: str) -> AuthResult:
    r = (reason or "").lower()
    if r in ("secret", "secret_ok"):
        return AuthResult.SECRET_OK
    if r in ("bad_secret", "unsigned") and os.getenv("AURORA_MESH_REQUIRE_AUTH", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return AuthResult.SECRET_BAD if r == "bad_secret" else AuthResult.UNSIGNED
    if r == "bad_secret":
        return AuthResult.SECRET_BAD
    if r == "fingerprint_mismatch":
        return AuthResult.FINGERPRINT_MISMATCH
    if r in ("not_object", "bad_magic", "no_node_id"):
        return AuthResult.MALFORMED
    if r in ("unsigned", "none"):
        return AuthResult.UNSIGNED
    return AuthResult.NONE


class GhostwalkService:
    def __init__(
        self,
        *,
        local_node_id: str = "local",
        trust_policy: Optional[TrustPolicy] = None,
        evidence_store=None,
        node_lookup: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        clock=None,
    ):
        self.local_node_id = local_node_id or "local"
        self.trust = TrustPolicyEngine(trust_policy or TrustPolicy(
            require_auth=os.getenv("AURORA_MESH_REQUIRE_AUTH", "0").lower() in ("1", "true", "yes", "on"),
        ))
        self.topology = TopologyEngine(local_node_id=self.local_node_id, clock=clock)
        self.anomalies = AnomalyEngine()
        self.evidence = EvidenceRecorder(local_node_id=self.local_node_id, store=evidence_store)
        self.recovery = RecoveryEngine(local_node_id=self.local_node_id)
        self._node_lookup = node_lookup

    def observe_peer_advertisement(
        self,
        node_id: str,
        *,
        fingerprint: str = "",
        auth_ok: bool = False,
        auth_reason: str = "",
        capabilities: Optional[List[str]] = None,
        endpoint: str = "",
        source: ObservationSource = ObservationSource.DIRECT,
    ) -> Dict[str, Any]:
        """Ingest a discovery/gateway-style advertisement."""
        auth = _map_auth_reason(auth_reason if not auth_ok else "secret")
        if auth_ok and auth == AuthResult.NONE:
            auth = AuthResult.SECRET_OK

        if auth == AuthResult.MALFORMED:
            f = self.anomalies.note_auth_failure(node_id or "?", reason="malformed")
            ev = self.evidence.record(
                "auth_failure",
                node_id or "?",
                decision="deny",
                rationale="malformed_identity",
            )
            return {"ok": False, "error": "malformed", "finding": f.to_dict(), "evidence": ev.to_dict()}

        existing = self.trust.get(node_id)
        if existing and fingerprint and existing.fingerprint and existing.fingerprint != fingerprint:
            f = self.anomalies.note_identity_conflict(
                node_id,
                expected_fp=existing.fingerprint,
                observed_fp=fingerprint,
            )
            ev = self.evidence.record(
                "identity_conflict",
                node_id,
                decision="quarantine",
                rationale="fingerprint_mismatch",
                observation_refs=[f.finding_id],
            )
            rec = self.trust.evaluate(
                node_id,
                fingerprint=fingerprint,
                auth_result=AuthResult.FINGERPRINT_MISMATCH,
                capabilities=capabilities,
                advertised_endpoint=endpoint,
                evidence_ref=ev.content_hash or ev.event_id,
            )
            prop = self.recovery.propose(
                "quarantine_peer",
                node_id,
                trigger_evidence=[ev.event_id, f.finding_id],
                expected_impact="stop elevating peer until operator confirms identity",
                authorization_required="operator",
                rollback="clear_quarantine after verified fingerprint update",
            )
            return {
                "ok": False,
                "peer": rec.to_dict(),
                "finding": f.to_dict(),
                "evidence": ev.to_dict(),
                "proposal": prop.to_dict(),
            }

        if auth in (AuthResult.SECRET_BAD,):
            f = self.anomalies.note_auth_failure(node_id, reason=auth_reason or "bad_secret")
            ev = self.evidence.record(
                "auth_failure",
                node_id,
                decision="deny",
                rationale=auth_reason or "bad_secret",
                observation_refs=[f.finding_id],
            )
            rec = self.trust.evaluate(
                node_id,
                fingerprint=fingerprint,
                auth_result=auth,
                capabilities=capabilities,
                advertised_endpoint=endpoint,
                evidence_ref=ev.content_hash or ev.event_id,
            )
            return {"ok": False, "peer": rec.to_dict(), "finding": f.to_dict(), "evidence": ev.to_dict()}

        kind = ObservationKind.PEER_AUTH if auth == AuthResult.SECRET_OK else ObservationKind.PEER_SEEN
        obs = self.topology.ingest(
            kind,
            node_id,
            source=source,
            payload={
                "capabilities": list(capabilities or []),
                "endpoint": endpoint,
                "fingerprint_prefix": (fingerprint or "")[:16],
            },
        )
        rec = self.trust.evaluate(
            node_id,
            fingerprint=fingerprint,
            auth_result=auth,
            capabilities=capabilities,
            advertised_endpoint=endpoint,
            evidence_ref=obs.evidence_ref or f"obs-{obs.sequence}",
        )
        ev = self.evidence.record(
            "peer_observation",
            node_id,
            decision=rec.trust_decision.value,
            rationale=f"auth={auth.value}; state={rec.identity_state.value}",
            observation_refs=[f"obs-{obs.sequence}"],
        )
        return {"ok": True, "peer": rec.to_dict(), "observation": obs.to_dict(), "evidence": ev.to_dict()}

    def observe_peer_lost(self, node_id: str, *, last_seen: float = 0.0) -> Dict[str, Any]:
        obs = self.topology.ingest(
            ObservationKind.PEER_LOST,
            node_id,
            payload={"last_seen": last_seen},
        )
        f = self.anomalies.note_peer_stale(node_id, last_seen=last_seen or obs.ts)
        ev = self.evidence.record(
            "peer_stale",
            node_id,
            decision="degrade",
            rationale="peer observation expired or lost",
            observation_refs=[f.finding_id, f"obs-{obs.sequence}"],
        )
        prop = self.recovery.propose(
            "mark_degraded",
            node_id,
            trigger_evidence=[ev.event_id, f.finding_id],
            expected_impact="prefer alternate routes; do not erase peer history",
            authorization_required="none_local_policy",
            rollback="automatic on fresh observation",
        )
        return {
            "ok": True,
            "observation": obs.to_dict(),
            "finding": f.to_dict(),
            "evidence": ev.to_dict(),
            "proposal": prop.to_dict(),
        }

    def observe_delivery_failure(self, node_id: str, *, consecutive: int) -> Dict[str, Any]:
        f = self.anomalies.note_delivery_failures(node_id, count=consecutive)
        if f is None:
            return {"ok": True, "finding": None, "note": "below_threshold"}
        ev = self.evidence.record(
            "delivery_failures",
            node_id,
            decision="recommend_failover",
            rationale=f"consecutive_failures={consecutive}",
            observation_refs=[f.finding_id],
        )
        prop = self.recovery.propose(
            "recommend_route_failover",
            node_id,
            trigger_evidence=[ev.event_id, f.finding_id],
            expected_impact="RouteManager cooldown + alternate selection",
            authorization_required="none_local_policy",
            rollback="route success clears failure counters",
        )
        return {"ok": True, "finding": f.to_dict(), "evidence": ev.to_dict(), "proposal": prop.to_dict()}

    def status(self) -> Dict[str, Any]:
        peers = self.trust.list_peers()
        snap = self.topology.snapshot(peer_records=peers)
        open_findings = self.anomalies.list_findings(open_only=True)
        return {
            "ok": True,
            "local_node_id": self.local_node_id,
            "peer_counts": self.trust.counts(),
            "topology": snap.to_dict(),
            "open_anomalies": len(open_findings),
            "findings": open_findings[:20],
            "proposals": self.recovery.list_proposals(active_only=True)[:20],
            "recent_evidence": self.evidence.recent(10),
            "trust_decisions": self.trust.recent_decisions()[-10:],
            "timeline": self.topology.timeline(20),
        }


_service: Optional[GhostwalkService] = None


def get_ghostwalk() -> Optional[GhostwalkService]:
    return _service


def init_ghostwalk(**kwargs) -> GhostwalkService:
    global _service
    _service = GhostwalkService(**kwargs)
    logger.info("ghostwalk initialized (local=%s)", _service.local_node_id)
    return _service
