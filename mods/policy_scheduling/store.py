"""Immutable policy version store.

In-process primary store; optional Redis mirror via CommsLayer when attached.
Versions are never mutated after leave-draft. Active reference is atomic.
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any, Dict, List, Optional

from .schema import AuditEntry, PolicyDocument, PolicyStatus, SimulationResult

# Working-copy statuses allowed in the draft slot (not yet active)
_WORKING = {
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

    def attach_comms(self, comms: Any) -> None:
        self._comms = comms

    def _mirror(self, key: str, value: Any) -> None:
        if self._comms is None:
            return
        try:
            self._comms.set_state(f"policy:{key}", value)
        except Exception:
            pass

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
        """Store an immutable version. Rejects overwrite of existing version_id."""
        with self._lock:
            if doc.version_id in self._versions:
                raise ValueError(f"Version {doc.version_id} is immutable")
            stored = doc.model_copy(deep=True)
            self._versions[doc.version_id] = stored
            self._mirror(f"version:{doc.version_id}", stored.model_dump())
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
        """Atomic active-policy update with optimistic concurrency."""
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
            doc = self._versions[version_id].mark(PolicyStatus.ACTIVE)
            self._versions[version_id] = doc
            self._active_id = version_id
            self._mirror("active_id", version_id)
            self._mirror(f"version:{version_id}", doc.model_dump())
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
            return entry.model_copy(deep=True)

    def list_audit(self, limit: int = 50) -> List[AuditEntry]:
        with self._lock:
            return [e.model_copy(deep=True) for e in reversed(self._audit[-limit:])]


class ConcurrentModificationError(Exception):
    pass
