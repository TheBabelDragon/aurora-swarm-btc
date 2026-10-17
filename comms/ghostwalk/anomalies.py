"""Deterministic anomaly engine — evidence, not guesswork.

Never labels a finding as an attack without sufficient evidence.
Severity and confidence are separate. Detection ≠ inference ≠ confirmed fact.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    INCONCLUSIVE = "inconclusive"


RULE_VERSION = "ghostwalk.rules.v1"


@dataclass
class AnomalyFinding:
    finding_id: str
    rule_id: str
    rule_version: str
    subject_id: str
    window_start: float
    window_end: float
    expected: str
    observed: str
    severity: Severity
    confidence: float  # 0.0–1.0; separate from severity
    evidence_refs: List[str] = field(default_factory=list)
    alternatives: List[str] = field(default_factory=list)
    status: FindingStatus = FindingStatus.OPEN
    what_would_change: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "subject_id": self.subject_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "expected": self.expected,
            "observed": self.observed,
            "severity": self.severity.value,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
            "alternatives": list(self.alternatives),
            "status": self.status.value,
            "what_would_change": self.what_would_change,
            "details": dict(self.details),
            # Explicit: not an attack claim
            "is_attack_claim": False,
        }


def _fid(rule_id: str, subject_id: str, window_key: str) -> str:
    raw = f"{rule_id}|{subject_id}|{window_key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class AnomalyEngine:
    def __init__(self, *, max_findings: int = 256, delivery_fail_threshold: int = 5):
        self.max_findings = max_findings
        self.delivery_fail_threshold = delivery_fail_threshold
        self._findings: Dict[str, AnomalyFinding] = {}
        self._open_keys: Set[str] = set()
        self._delivery_fails: Dict[str, int] = {}

    def _put(self, f: AnomalyFinding) -> AnomalyFinding:
        key = f"{f.rule_id}:{f.subject_id}"
        if key in self._open_keys and f.finding_id in self._findings:
            # refresh window, do not duplicate
            existing = self._findings[f.finding_id]
            existing.window_end = f.window_end
            existing.observed = f.observed
            existing.evidence_refs = list(
                dict.fromkeys(existing.evidence_refs + f.evidence_refs)
            )[-16:]
            return existing
        self._findings[f.finding_id] = f
        if f.status == FindingStatus.OPEN:
            self._open_keys.add(key)
        while len(self._findings) > self.max_findings:
            oldest = next(iter(self._findings))
            del self._findings[oldest]
        return f

    def note_peer_stale(
        self,
        subject_id: str,
        *,
        last_seen: float,
        now: Optional[float] = None,
        evidence_ref: str = "",
    ) -> AnomalyFinding:
        now = now if now is not None else time.time()
        fid = _fid("peer_stale", subject_id, str(int(last_seen // 60)))
        return self._put(
            AnomalyFinding(
                finding_id=fid,
                rule_id="peer_stale",
                rule_version=RULE_VERSION,
                subject_id=subject_id,
                window_start=last_seen,
                window_end=now,
                expected="fresh peer observation within TTL",
                observed=f"no fresh observation since {last_seen}",
                severity=Severity.LOW,
                confidence=0.6,
                evidence_refs=[evidence_ref] if evidence_ref else [],
                alternatives=[
                    "temporary network partition",
                    "peer shut down cleanly",
                    "clock skew on observer",
                ],
                what_would_change="a fresh authenticated observation from this peer",
            )
        )

    def note_identity_conflict(
        self,
        subject_id: str,
        *,
        expected_fp: str,
        observed_fp: str,
        now: Optional[float] = None,
        evidence_ref: str = "",
    ) -> AnomalyFinding:
        now = now if now is not None else time.time()
        fid = _fid("identity_conflict", subject_id, observed_fp[:16])
        return self._put(
            AnomalyFinding(
                finding_id=fid,
                rule_id="identity_conflict",
                rule_version=RULE_VERSION,
                subject_id=subject_id,
                window_start=now,
                window_end=now,
                expected=f"fingerprint {expected_fp[:16]}…",
                observed=f"fingerprint {observed_fp[:16]}…",
                severity=Severity.HIGH,
                confidence=0.85,
                evidence_refs=[evidence_ref] if evidence_ref else [],
                alternatives=[
                    "legitimate key rotation not yet recorded",
                    "two nodes sharing node_id",
                    "malicious impostor (unconfirmed)",
                ],
                what_would_change="operator-confirmed fingerprint update or revocation",
                details={"expected_fp_prefix": expected_fp[:16], "observed_fp_prefix": observed_fp[:16]},
            )
        )

    def note_auth_failure(
        self,
        subject_id: str,
        *,
        reason: str,
        now: Optional[float] = None,
        evidence_ref: str = "",
    ) -> AnomalyFinding:
        now = now if now is not None else time.time()
        fid = _fid("auth_failure", subject_id, reason[:32])
        return self._put(
            AnomalyFinding(
                finding_id=fid,
                rule_id="auth_failure",
                rule_version=RULE_VERSION,
                subject_id=subject_id,
                window_start=now,
                window_end=now,
                expected="valid authentication for advertisement",
                observed=reason[:120],
                severity=Severity.MEDIUM,
                confidence=0.8,
                evidence_refs=[evidence_ref] if evidence_ref else [],
                alternatives=["misconfigured secret on peer", "stale beacon", "active probe"],
                what_would_change="successful authenticated advertisement from subject",
            )
        )

    def note_gateway_capability_change(
        self,
        gateway_id: str,
        *,
        before: List[str],
        after: List[str],
        now: Optional[float] = None,
        evidence_ref: str = "",
    ) -> AnomalyFinding:
        now = now if now is not None else time.time()
        fid = _fid("gateway_cap_change", gateway_id, ",".join(sorted(after))[:40])
        return self._put(
            AnomalyFinding(
                finding_id=fid,
                rule_id="gateway_capability_change",
                rule_version=RULE_VERSION,
                subject_id=gateway_id,
                window_start=now,
                window_end=now,
                expected=f"capabilities {before}",
                observed=f"capabilities {after}",
                severity=Severity.MEDIUM,
                confidence=0.7,
                evidence_refs=[evidence_ref] if evidence_ref else [],
                alternatives=["planned upgrade", "partial advertisement", "compromised gateway (unconfirmed)"],
                what_would_change="stable repeated advertisements matching policy allow-list",
            )
        )

    def note_delivery_failures(
        self,
        subject_id: str,
        *,
        count: int,
        now: Optional[float] = None,
        evidence_ref: str = "",
    ) -> Optional[AnomalyFinding]:
        self._delivery_fails[subject_id] = count
        if count < self.delivery_fail_threshold:
            return None
        now = now if now is not None else time.time()
        fid = _fid("delivery_failures", subject_id, str(count // self.delivery_fail_threshold))
        return self._put(
            AnomalyFinding(
                finding_id=fid,
                rule_id="delivery_failures",
                rule_version=RULE_VERSION,
                subject_id=subject_id,
                window_start=now - 60,
                window_end=now,
                expected=f"fewer than {self.delivery_fail_threshold} consecutive delivery failures",
                observed=f"{count} consecutive failures",
                severity=Severity.MEDIUM,
                confidence=0.75,
                evidence_refs=[evidence_ref] if evidence_ref else [],
                alternatives=["peer offline", "route cooldown", "transient congestion"],
                what_would_change="successful DELIVERED or ACCEPTED outcome to subject",
            )
        )

    def note_policy_endpoint_violation(
        self,
        subject_id: str,
        *,
        endpoint: str,
        reason: str,
        now: Optional[float] = None,
        evidence_ref: str = "",
    ) -> AnomalyFinding:
        now = now if now is not None else time.time()
        fid = _fid("policy_endpoint", subject_id, endpoint[:40])
        return self._put(
            AnomalyFinding(
                finding_id=fid,
                rule_id="policy_endpoint_violation",
                rule_version=RULE_VERSION,
                subject_id=subject_id,
                window_start=now,
                window_end=now,
                expected="endpoint within configured network policy",
                observed=f"{endpoint[:80]} ({reason})",
                severity=Severity.HIGH,
                confidence=0.9,
                evidence_refs=[evidence_ref] if evidence_ref else [],
                alternatives=["misconfigured peer", "intentional probe"],
                what_would_change="advertisement of policy-compliant endpoint",
            )
        )

    def note_conflicting_observations(
        self,
        subject_id: str,
        *,
        summary: str,
        now: Optional[float] = None,
        evidence_refs: Optional[List[str]] = None,
    ) -> AnomalyFinding:
        now = now if now is not None else time.time()
        fid = _fid("conflicting_obs", subject_id, summary[:40])
        return self._put(
            AnomalyFinding(
                finding_id=fid,
                rule_id="conflicting_observations",
                rule_version=RULE_VERSION,
                subject_id=subject_id,
                window_start=now,
                window_end=now,
                expected="consistent observations across peers",
                observed=summary[:200],
                severity=Severity.MEDIUM,
                confidence=0.55,
                evidence_refs=list(evidence_refs or []),
                alternatives=["partition healing", "clock skew", "lying peer (unconfirmed)"],
                what_would_change="corroborating direct observations from multiple authenticated peers",
            )
        )

    def resolve(self, finding_id: str, *, reason: str = "") -> Optional[AnomalyFinding]:
        f = self._findings.get(finding_id)
        if not f:
            return None
        f.status = FindingStatus.RESOLVED
        f.details["resolved_reason"] = reason[:200]
        key = f"{f.rule_id}:{f.subject_id}"
        self._open_keys.discard(key)
        return f

    def acknowledge(self, finding_id: str) -> Optional[AnomalyFinding]:
        f = self._findings.get(finding_id)
        if not f:
            return None
        f.status = FindingStatus.ACKNOWLEDGED
        return f

    def list_findings(self, *, open_only: bool = False) -> List[Dict[str, Any]]:
        out = []
        for f in self._findings.values():
            if open_only and f.status not in (FindingStatus.OPEN, FindingStatus.ACKNOWLEDGED):
                continue
            out.append(f.to_dict())
        return out
