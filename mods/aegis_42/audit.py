"""Append-only incident records, integrity verification, decision provenance."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class AuditRecord(BaseModel):
    record_id: str = Field(default_factory=lambda: f"ar-{time.time_ns()}")
    ts: float = Field(default_factory=time.time)
    kind: str  # decision | containment | incident | integrity | system
    event_id: Optional[str] = None
    decision_id: Optional[str] = None
    actor_id: Optional[str] = None
    summary: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    prev_hash: str = ""
    record_hash: str = ""

    def compute_hash(self) -> str:
        body = {
            "record_id": self.record_id,
            "ts": self.ts,
            "kind": self.kind,
            "event_id": self.event_id,
            "decision_id": self.decision_id,
            "actor_id": self.actor_id,
            "summary": self.summary,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
        }
        return content_hash(body)


class AuditLog:
    """Append-only, hash-chained audit log. Tamper detection via chain verification."""

    def __init__(self, max_records: int = 2000):
        self._records: List[AuditRecord] = []
        self._max = max_records
        self._head_hash = "genesis"

    def append(
        self,
        kind: str,
        summary: str,
        *,
        event_id: Optional[str] = None,
        decision_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> AuditRecord:
        rec = AuditRecord(
            kind=kind,
            summary=summary,
            event_id=event_id,
            decision_id=decision_id,
            actor_id=actor_id,
            payload=payload or {},
            prev_hash=self._head_hash,
        )
        rec.record_hash = rec.compute_hash()
        self._records.append(rec)
        self._head_hash = rec.record_hash
        if len(self._records) > self._max:
            # Keep chain integrity: drop oldest but re-anchor is out of scope for v0
            self._records = self._records[-self._max:]
        return rec

    def verify_integrity(self) -> Dict[str, Any]:
        """Walk the chain; report first break if any."""
        if not self._records:
            return {"ok": True, "records": 0, "head": self._head_hash}
        expected_prev = "genesis"
        for i, rec in enumerate(self._records):
            if rec.prev_hash != expected_prev:
                return {
                    "ok": False,
                    "broken_at": i,
                    "record_id": rec.record_id,
                    "expected_prev": expected_prev,
                    "actual_prev": rec.prev_hash,
                }
            computed = rec.compute_hash()
            if computed != rec.record_hash:
                return {
                    "ok": False,
                    "broken_at": i,
                    "record_id": rec.record_id,
                    "reason": "record_hash mismatch",
                    "computed": computed,
                    "stored": rec.record_hash,
                }
            expected_prev = rec.record_hash
        return {"ok": True, "records": len(self._records), "head": self._head_hash}

    def recent(self, limit: int = 50) -> List[AuditRecord]:
        return list(reversed(self._records[-limit:]))

    def find_by_event(self, event_id: str) -> List[AuditRecord]:
        return [r for r in self._records if r.event_id == event_id]
