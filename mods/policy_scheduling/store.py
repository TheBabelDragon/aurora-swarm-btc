"""Immutable policy version store with optional Redis durability.

When CommsLayer is attached, versions / active_id / audit are mirrored to
Redis keys under policy:* and reloaded on attach (restart-safe when Redis
persists). In-process remains the primary working set.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from .schema import AuditEntry, PolicyDocument, PolicyStatus, SimulationResult

logger = logging.getLogger("aurora.policy.store")

_WORKING = {
    PolicyStatus.DRAFT,
    PolicyStatus.SIMULATED,
    PolicyStatus.VALIDATED,
    PolicyStatus.PENDING_APPROVAL,
    PolicyStatus.REJECTED,
}

_PRE_ACTIVE = {
    PolicyStatus.DRAFT,
    PolicyStatus.SIMULATED,
    PolicyStatus.VALIDATED,
    PolicyStatus.PENDING_APPROVAL,
    PolicyStatus.REJECTED,
}


class PolicyStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._versions: Dict[str, PolicyDocument] = {}
        self._active_id: Optional[str] = None
        self._draft: Optional[PolicyDocument] = None
        self._simulations: Dict[str, SimulationResult] = {}
        self._audit: List[AuditEntry] = []
        self._max_audit = 2000
        self._comms = None
        self._durable = False

    def attach_comms(self, comms: Any) -> None:
        self._comms = comms
        self._load_from_redis()

    @property
    def durable(self) -> bool:
        return self._durable

    def _mirror(self, key: str, value: Any) -> None:
        if self._comms is None:
            return
        try:
            self._comms.set_state(f"policy:{key}", value)
            self._durable = True
        except Exception as e:
            logger.debug("policy mirror failed: %s", e)

    def _load_from_redis(self) -> None:
        if self._comms is None:
            return
        try:
            index = self._comms.get_state("policy:version_index")
            if isinstance(index, list):
                for vid in index:
                    raw = self._comms.get_state(f"policy:version:{vid}")
                    if isinstance(raw, dict):
                        try:
                            doc = PolicyDocument.model_validate(raw)
                            self._versions[doc.version_id] = doc
                        except Exception:
                            continue
            active = self._comms.get_state("policy:active_id")
            if isinstance(active, str) and active in self._versions:
                self._active_id = active
            draft_raw = self._comms.get_state("policy:draft")
            if isinstance(draft_raw, dict):
                try:
                    self._draft = PolicyDocument.model_validate(draft_raw)
                except Exception:
                    self._draft = None
            audit_raw = self._comms.get_state("policy:audit")
            if isinstance(audit_raw, list):
                for item in audit_raw:
                    try:
                        self._audit.append(AuditEntry.model_validate(item))
                    except Exception:
                        continue
            self._durable = True
            logger.info(
                "policy store loaded from Redis (versions=%s active=%s audit=%s)",
                len(self._versions),
                self._active_id,
                len(self._audit),
            )
        except Exception as e:
            logger.warning("policy Redis load skipped: %s", e)
            self._durable = False

    def _persist_index(self) -> None:
        self._mirror("version_index", list(self._versions.keys()))
        self._mirror("active_id", self._active_id)
        self._mirror(
            "audit",
            [e.model_dump() for e in self._audit[-self._max_audit :]],
        )

    def get_draft(self) -> Optional[PolicyDocument]:
        with self._lock:
            return self._draft.model_copy(deep=True) if self._draft else None

    def set_draft(self, doc: PolicyDocument) -> PolicyDocument:
        with self._lock:
            if doc.status not in _WORKING:
                raise ValueError(f"Working draft cannot hold status {doc.status}")
            self._draft = doc.model_copy(deep=True)
            self._mirror("draft", self._draft.model_dump())
            return self._draft.model_copy(deep=True)

    def discard_draft(self) -> None:
        with self._lock:
            self._draft = None
            self._mirror("draft", None)

    def put_version(self, doc: PolicyDocument) -> PolicyDocument:
        with self._lock:
            existing = self._versions.get(doc.version_id)
            if existing is not None:
                if existing.status in (PolicyStatus.ACTIVE, PolicyStatus.SUPERSEDED):
                    raise ValueError(f"Version {doc.version_id} is immutable")
                if existing.status not in _PRE_ACTIVE:
                    raise ValueError(f"Version {doc.version_id} is immutable")
            stored = doc.model_copy(deep=True)
            self._versions[doc.version_id] = stored
            self._mirror(f"version:{doc.version_id}", stored.model_dump())
            self._persist_index()
            return stored.model_copy(deep=True)

    def get_version(self, version_id: str) -> Optional[PolicyDocument]:
        with self._lock:
            v = self._versions.get(version_id)
            return v.model_copy(deep=True) if v else None

    def list_versions(self) -> List[PolicyDocument]:
        with self._lock:
            items = sorted(self._versions.values(), key=lambda d: d.created_at, reverse=True)
            return [v.model_copy(deep=True) for v in items]

    def get_active(self) -> Optional[PolicyDocument]:
        with self._lock:
            if not self._active_id:
                return None
            v = self._versions.get(self._active_id)
            return v.model_copy(deep=True) if v else None

    def active_version_id(self) -> Optional[str]:
        with self._lock:
            return self._active_id

    def set_active(
        self,
        version_id: str,
        *,
        expected_active: Optional[str] = None,
    ) -> PolicyDocument:
        with self._lock:
            if expected_active is not None and self._active_id != expected_active:
                raise ConcurrentModificationError(
                    f"expected active={expected_active!r} actual={self._active_id!r}"
                )
            if version_id not in self._versions:
                raise KeyError(f"Unknown policy version {version_id}")
            if self._active_id and self._active_id in self._versions:
                prior = self._versions[self._active_id]
                if prior.status == PolicyStatus.ACTIVE:
                    self._versions[self._active_id] = prior.mark(PolicyStatus.SUPERSEDED)
                    self._mirror(
                        f"version:{self._active_id}",
                        self._versions[self._active_id].model_dump(),
                    )
            doc = self._versions[version_id].mark(PolicyStatus.ACTIVE)
            self._versions[version_id] = doc
            self._active_id = version_id
            self._mirror(f"version:{version_id}", doc.model_dump())
            self._persist_index()
            return doc.model_copy(deep=True)

    def put_simulation(self, sim: SimulationResult) -> SimulationResult:
        with self._lock:
            self._simulations[sim.simulation_id] = sim.model_copy(deep=True)
            return sim.model_copy(deep=True)

    def get_simulation(self, simulation_id: str) -> Optional[SimulationResult]:
        with self._lock:
            s = self._simulations.get(simulation_id)
            return s.model_copy(deep=True) if s else None

    def append_audit(self, entry: AuditEntry) -> AuditEntry:
        with self._lock:
            self._audit.append(entry)
            if len(self._audit) > self._max_audit:
                self._audit = self._audit[-self._max_audit :]
            self._mirror("audit", [e.model_dump() for e in self._audit])
            return entry.model_copy(deep=True)

    def list_audit(self, limit: int = 50) -> List[AuditEntry]:
        with self._lock:
            return [e.model_copy(deep=True) for e in reversed(self._audit[-limit:])]


class ConcurrentModificationError(Exception):
    pass
