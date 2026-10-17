"""Stable peer identity and explicit trust policy.

Authenticated discovery proves possession of the configured mesh secret;
it does not establish that a peer is trustworthy. Identity, authentication,
authorization, reachability, and reputation remain separate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class IdentityState(str, Enum):
    UNKNOWN = "unknown"
    OBSERVED = "observed"
    AUTHENTICATED = "authenticated"
    UNVERIFIED = "unverified"
    CONFLICT = "conflict"
    REVOKED = "revoked"
    QUARANTINED = "quarantined"


class AuthResult(str, Enum):
    NONE = "none"
    UNSIGNED = "unsigned"
    SECRET_OK = "secret_ok"
    SECRET_BAD = "secret_bad"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    MALFORMED = "malformed"


class TrustDecision(str, Enum):
    ALLOW = "allow"
    DEFER = "defer"
    DENY = "deny"
    QUARANTINE = "quarantine"


@dataclass
class TrustPolicy:
    """Explicit, deterministic trust rules (no silent elevation)."""

    require_auth: bool = False
    allow_unsigned: bool = True
    quarantine_on_fingerprint_mismatch: bool = True
    quarantine_on_identity_conflict: bool = True
    max_peer_records: int = 512
    default_ttl_s: float = 300.0
    policy_version: str = "ghostwalk.trust.v1"


@dataclass
class PeerRecord:
    """One peer as known to this node — evidence-backed, time-aware."""

    node_id: str
    fingerprint: str = ""
    advertised_endpoint: str = ""
    capabilities: List[str] = field(default_factory=list)
    identity_state: IdentityState = IdentityState.UNKNOWN
    auth_result: AuthResult = AuthResult.NONE
    trust_decision: TrustDecision = TrustDecision.DEFER
    last_observation_at: float = 0.0
    last_success_at: float = 0.0
    expires_at: float = 0.0
    quarantine_reason: str = ""
    revoked: bool = False
    evidence_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_fresh(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        if self.expires_at <= 0:
            return True
        return now < self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "fingerprint": self.fingerprint,
            "advertised_endpoint": self.advertised_endpoint,
            "capabilities": list(self.capabilities),
            "identity_state": self.identity_state.value,
            "auth_result": self.auth_result.value,
            "trust_decision": self.trust_decision.value,
            "last_observation_at": self.last_observation_at,
            "last_success_at": self.last_success_at,
            "expires_at": self.expires_at,
            "quarantine_reason": self.quarantine_reason,
            "revoked": self.revoked,
            "evidence_refs": list(self.evidence_refs),
            "fresh": self.is_fresh(),
            "metadata": dict(self.metadata),
        }


class TrustPolicyEngine:
    """Deterministic, explainable trust decisions."""

    def __init__(self, policy: Optional[TrustPolicy] = None):
        self.policy = policy or TrustPolicy()
        self._peers: Dict[str, PeerRecord] = {}
        self._decision_log: List[Dict[str, Any]] = []
        self._max_log = 256

    def evaluate(
        self,
        node_id: str,
        *,
        fingerprint: str = "",
        auth_result: AuthResult = AuthResult.NONE,
        capabilities: Optional[List[str]] = None,
        advertised_endpoint: str = "",
        now: Optional[float] = None,
        evidence_ref: str = "",
    ) -> PeerRecord:
        now = now if now is not None else time.time()
        nid = (node_id or "").strip()
        if not nid or len(nid) > 256:
            raise ValueError("malformed node_id")

        existing = self._peers.get(nid)
        rationale: List[str] = []

        if auth_result == AuthResult.MALFORMED:
            decision = TrustDecision.DENY
            state = IdentityState.UNVERIFIED
            rationale.append("malformed_identity")
        elif auth_result == AuthResult.SECRET_BAD:
            decision = TrustDecision.DENY
            state = IdentityState.UNVERIFIED
            rationale.append("authentication_failed")
        elif auth_result == AuthResult.FINGERPRINT_MISMATCH:
            decision = (
                TrustDecision.QUARANTINE
                if self.policy.quarantine_on_fingerprint_mismatch
                else TrustDecision.DENY
            )
            state = IdentityState.CONFLICT
            rationale.append("fingerprint_mismatch")
        elif existing and existing.fingerprint and fingerprint and existing.fingerprint != fingerprint:
            decision = (
                TrustDecision.QUARANTINE
                if self.policy.quarantine_on_identity_conflict
                else TrustDecision.DENY
            )
            state = IdentityState.CONFLICT
            rationale.append("identity_conflict")
        elif existing and existing.revoked:
            decision = TrustDecision.DENY
            state = IdentityState.REVOKED
            rationale.append("revoked")
        elif existing and existing.identity_state == IdentityState.QUARANTINED:
            decision = TrustDecision.QUARANTINE
            state = IdentityState.QUARANTINED
            rationale.append("already_quarantined")
        elif auth_result == AuthResult.SECRET_OK:
            decision = TrustDecision.ALLOW
            state = IdentityState.AUTHENTICATED
            rationale.append("secret_authenticated")
        elif self.policy.require_auth:
            decision = TrustDecision.DENY
            state = IdentityState.UNVERIFIED
            rationale.append("auth_required")
        elif auth_result in (AuthResult.UNSIGNED, AuthResult.NONE) and not self.policy.allow_unsigned:
            decision = TrustDecision.DENY
            state = IdentityState.UNVERIFIED
            rationale.append("unsigned_rejected")
        else:
            decision = TrustDecision.DEFER
            state = IdentityState.OBSERVED if auth_result != AuthResult.NONE else IdentityState.UNKNOWN
            rationale.append("observed_unverified")

        rec = PeerRecord(
            node_id=nid,
            fingerprint=fingerprint or (existing.fingerprint if existing else ""),
            advertised_endpoint=advertised_endpoint or (existing.advertised_endpoint if existing else ""),
            capabilities=list(capabilities or (existing.capabilities if existing else [])),
            identity_state=state,
            auth_result=auth_result,
            trust_decision=decision,
            last_observation_at=now,
            last_success_at=(
                now
                if decision == TrustDecision.ALLOW
                else (existing.last_success_at if existing else 0.0)
            ),
            expires_at=now + self.policy.default_ttl_s,
            quarantine_reason=(
                ";".join(rationale)
                if decision == TrustDecision.QUARANTINE
                else (existing.quarantine_reason if existing else "")
            ),
            revoked=bool(existing.revoked) if existing else False,
            evidence_refs=list(existing.evidence_refs) if existing else [],
            metadata=dict(existing.metadata) if existing else {},
        )
        if evidence_ref:
            rec.evidence_refs.append(evidence_ref)
            if len(rec.evidence_refs) > 32:
                rec.evidence_refs = rec.evidence_refs[-32:]

        self._peers[nid] = rec
        self._trim()
        self._log_decision(rec, rationale, now)
        return rec

    def quarantine(self, node_id: str, reason: str, *, evidence_ref: str = "") -> Optional[PeerRecord]:
        rec = self._peers.get(node_id)
        if rec is None:
            return None
        rec.identity_state = IdentityState.QUARANTINED
        rec.trust_decision = TrustDecision.QUARANTINE
        rec.quarantine_reason = reason[:200]
        if evidence_ref:
            rec.evidence_refs.append(evidence_ref)
        self._log_decision(rec, ["manual_quarantine", reason], time.time())
        return rec

    def revoke(self, node_id: str, reason: str, *, evidence_ref: str = "") -> Optional[PeerRecord]:
        rec = self._peers.get(node_id)
        if rec is None:
            return None
        rec.revoked = True
        rec.identity_state = IdentityState.REVOKED
        rec.trust_decision = TrustDecision.DENY
        rec.quarantine_reason = reason[:200]
        if evidence_ref:
            rec.evidence_refs.append(evidence_ref)
        self._log_decision(rec, ["revoke", reason], time.time())
        return rec

    def clear_quarantine(self, node_id: str, *, evidence_ref: str = "") -> Optional[PeerRecord]:
        rec = self._peers.get(node_id)
        if rec is None or rec.revoked:
            return rec
        if rec.identity_state != IdentityState.QUARANTINED:
            return rec
        rec.identity_state = IdentityState.OBSERVED
        rec.trust_decision = TrustDecision.DEFER
        rec.quarantine_reason = ""
        if evidence_ref:
            rec.evidence_refs.append(evidence_ref)
        self._log_decision(rec, ["clear_quarantine"], time.time())
        return rec

    def get(self, node_id: str) -> Optional[PeerRecord]:
        return self._peers.get(node_id)

    def list_peers(self) -> Dict[str, Dict[str, Any]]:
        return {k: v.to_dict() for k, v in self._peers.items()}

    def counts(self) -> Dict[str, int]:
        c = {
            "total": len(self._peers),
            "authenticated": 0,
            "unverified": 0,
            "stale": 0,
            "quarantined": 0,
            "revoked": 0,
            "conflict": 0,
        }
        now = time.time()
        for p in self._peers.values():
            if p.identity_state == IdentityState.AUTHENTICATED:
                c["authenticated"] += 1
            if p.identity_state in (IdentityState.UNVERIFIED, IdentityState.UNKNOWN, IdentityState.OBSERVED):
                c["unverified"] += 1
            if not p.is_fresh(now):
                c["stale"] += 1
            if p.identity_state == IdentityState.QUARANTINED:
                c["quarantined"] += 1
            if p.revoked or p.identity_state == IdentityState.REVOKED:
                c["revoked"] += 1
            if p.identity_state == IdentityState.CONFLICT:
                c["conflict"] += 1
        return c

    def recent_decisions(self) -> List[Dict[str, Any]]:
        return list(self._decision_log)

    def _trim(self) -> None:
        while len(self._peers) > self.policy.max_peer_records:
            oldest = min(self._peers.values(), key=lambda p: p.last_observation_at or 0)
            del self._peers[oldest.node_id]

    def _log_decision(self, rec: PeerRecord, rationale: List[str], now: float) -> None:
        self._decision_log.append(
            {
                "ts": now,
                "node_id": rec.node_id,
                "trust_decision": rec.trust_decision.value,
                "identity_state": rec.identity_state.value,
                "auth_result": rec.auth_result.value,
                "rationale": list(rationale),
                "policy_version": self.policy.policy_version,
            }
        )
        if len(self._decision_log) > self._max_log:
            self._decision_log = self._decision_log[-self._max_log :]
