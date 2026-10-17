"""Evidence receipts for Ghostwalk decisions — integrates mods/evidence_integrity.

Content hash is identity of the payload, not proof of authorship.
Authenticated ads are not proof that claims are true.
Persistence status is reported honestly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA_EVENT = "aurora.ghostwalk.evidence"
SCHEMA_VERSION = "0.1.0"

# Keys never allowed in receipts or logs
_REDACT = frozenset(
    {
        "secret",
        "password",
        "token",
        "api_key",
        "sig",
        "signature",
        "redis_url",
        "REDIS_URL",
        "AURORA_MESH_SECRET",
        "bearer",
        "authorization",
    }
)


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if k in _REDACT or lk in {x.lower() for x in _REDACT} or "secret" in lk or "password" in lk:
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


@dataclass
class GhostwalkEvidence:
    event_type: str
    event_id: str
    observer_id: str
    subject_id: str
    ts: float
    policy_version: str
    rule_version: str
    observation_refs: List[str] = field(default_factory=list)
    decision: str = ""
    rationale: str = ""
    action_result: str = "none"
    limitations: List[str] = field(default_factory=list)
    content_hash: str = ""
    persisted: bool = False
    persist_error: str = ""

    def to_payload(self) -> Dict[str, Any]:
        return _redact(
            {
                "schema": SCHEMA_EVENT,
                "schema_version": SCHEMA_VERSION,
                "event_type": self.event_type,
                "event_id": self.event_id,
                "observer_id": self.observer_id,
                "subject_id": self.subject_id,
                "ts": self.ts,
                "policy_version": self.policy_version,
                "rule_version": self.rule_version,
                "observation_refs": list(self.observation_refs),
                "decision": self.decision,
                "rationale": self.rationale,
                "action_result": self.action_result,
                "limitations": list(self.limitations),
            }
        )

    def to_dict(self) -> Dict[str, Any]:
        d = self.to_payload()
        d["content_hash"] = self.content_hash
        d["persisted"] = self.persisted
        d["persist_error"] = self.persist_error
        d["persistence_status"] = evidence_persistence_status(self.persisted, self.persist_error)
        return d


def evidence_persistence_status(persisted: bool, error: str = "") -> str:
    if persisted:
        return "durable"
    if error:
        return f"memory_only:{error[:80]}"
    return "memory_only"


class EvidenceRecorder:
    """Build and optionally persist Ghostwalk evidence via EvidenceStore."""

    def __init__(self, *, local_node_id: str = "local", store=None):
        self.local_node_id = local_node_id
        self._store = store
        self._memory: List[GhostwalkEvidence] = []
        self._max_memory = 256
        self._seq = 0

    def record(
        self,
        event_type: str,
        subject_id: str,
        *,
        decision: str = "",
        rationale: str = "",
        observation_refs: Optional[List[str]] = None,
        policy_version: str = "ghostwalk.trust.v1",
        rule_version: str = "ghostwalk.rules.v1",
        action_result: str = "none",
        limitations: Optional[List[str]] = None,
        event_id: str = "",
    ) -> GhostwalkEvidence:
        self._seq += 1
        now = time.time()
        eid = event_id or f"gw-{self.local_node_id}-{self._seq}-{int(now)}"
        ev = GhostwalkEvidence(
            event_type=event_type,
            event_id=eid,
            observer_id=self.local_node_id,
            subject_id=subject_id,
            ts=now,
            policy_version=policy_version,
            rule_version=rule_version,
            observation_refs=list(observation_refs or []),
            decision=decision,
            rationale=rationale[:500],
            action_result=action_result,
            limitations=list(limitations or []),
        )
        payload = ev.to_payload()
        try:
            from mods.evidence_integrity import build_evidence_object, verify_integrity

            obj = build_evidence_object(
                payload,
                node_id=self.local_node_id,
                sequence=self._seq,
                evidence_refs=[{"ref": r} for r in ev.observation_refs],
            )
            status = verify_integrity(obj)
            ev.content_hash = obj.content_hash
            if self._store is not None:
                try:
                    self._store.append(obj)
                    ev.persisted = True
                except Exception as e:
                    ev.persisted = False
                    ev.persist_error = str(e)[:120]
                    ev.limitations.append("evidence_store_append_failed")
            else:
                ev.persisted = False
                ev.limitations.append("no_evidence_store_configured")
            if status.value != "VALID":
                ev.limitations.append(f"integrity_status:{status.value}")
        except Exception as e:
            ev.persisted = False
            ev.persist_error = str(e)[:120]
            ev.limitations.append("evidence_integrity_unavailable")

        self._memory.append(ev)
        if len(self._memory) > self._max_memory:
            self._memory = self._memory[-self._max_memory :]
        return ev

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._memory[-max(1, limit) :]]
