"""Changeset lifecycle.

Never silently resolve semantic conflicts.
Never automatically promote an unverified changeset.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Set

from conflux.models.changeset import Changeset, ChangesetStatus, FileChange
from conflux.storage.persistence import ConfluxStore


class ChangesetCoordinator:
    def __init__(self, store: ConfluxStore) -> None:
        self.store = store
        self._col = "changesets"

    def create(self, cs: Changeset) -> Changeset:
        cs.status = ChangesetStatus.PROPOSED
        cs.updated_at = time.time()
        self.store.put(self._col, cs.changeset_id, cs.to_dict())
        return cs

    def get(self, changeset_id: str) -> Optional[Changeset]:
        d = self.store.get(self._col, changeset_id)
        return Changeset.from_dict(d) if d else None

    def list(
        self,
        *,
        project_id: str = "",
        status: str = "",
        limit: int = 50,
    ) -> List[Changeset]:
        values = self.store.list_values(self._col, limit=limit * 2)
        out: List[Changeset] = []
        for v in values:
            cs = Changeset.from_dict(v)
            if project_id and cs.project_id != project_id:
                continue
            if status and cs.status.value != status:
                continue
            out.append(cs)
            if len(out) >= limit:
                break
        return out

    def detect_conflicts(self, a: Changeset, b: Changeset) -> List[str]:
        """Path-level conflict detection. Semantic resolution is never automatic."""
        if a.project_id != b.project_id or a.source_id != b.source_id:
            return []
        if a.base_revision_id != b.base_revision_id:
            # Different bases — potential conflict on overlapping paths
            pass
        paths_a = {f.path for f in a.files}
        paths_b = {f.path for f in b.files}
        return sorted(paths_a & paths_b)

    def reconcile(
        self,
        changeset_id: str,
        *,
        peer_ids: Optional[List[str]] = None,
    ) -> dict:
        """Plan reconciliation. Does not auto-merge."""
        cs = self.get(changeset_id)
        if not cs:
            return {"ok": False, "error": "changeset_not_found"}
        peers = peer_ids or []
        conflicts: Dict[str, List[str]] = {}
        for pid in peers:
            peer = self.get(pid)
            if not peer:
                continue
            cpaths = self.detect_conflicts(cs, peer)
            if cpaths:
                conflicts[pid] = cpaths
        if conflicts:
            all_paths: Set[str] = set()
            for paths in conflicts.values():
                all_paths.update(paths)
            cs.status = ChangesetStatus.CONFLICTING
            cs.conflict_paths = sorted(all_paths)
            cs.updated_at = time.time()
            self.store.put(self._col, cs.changeset_id, cs.to_dict())
            return {
                "ok": False,
                "status": cs.status.value,
                "conflicts": conflicts,
                "message": "semantic conflicts require explicit resolution",
            }
        cs.status = ChangesetStatus.RECONCILED
        cs.conflict_paths = []
        cs.updated_at = time.time()
        self.store.put(self._col, cs.changeset_id, cs.to_dict())
        return {"ok": True, "status": cs.status.value, "conflicts": {}}

    def approve(
        self,
        changeset_id: str,
        *,
        approved_by: str,
        require_verified: bool = True,
    ) -> dict:
        cs = self.get(changeset_id)
        if not cs:
            return {"ok": False, "error": "changeset_not_found"}
        if cs.status == ChangesetStatus.CONFLICTING:
            return {"ok": False, "error": "cannot_approve_conflicting"}
        if require_verified and cs.verification_status not in ("passed", "advisory"):
            return {"ok": False, "error": "changeset_not_verified"}
        if cs.status not in (
            ChangesetStatus.RECONCILED,
            ChangesetStatus.VERIFIED,
            ChangesetStatus.PROPOSED,
        ):
            return {"ok": False, "error": f"invalid_status:{cs.status.value}"}
        cs.status = ChangesetStatus.APPROVED
        cs.approval_status = "approved"
        cs.approved_by = approved_by
        cs.approved_at = time.time()
        cs.updated_at = time.time()
        self.store.put(self._col, cs.changeset_id, cs.to_dict())
        return {"ok": True, "changeset": cs.to_dict()}

    def mark_verified(self, changeset_id: str, *, status: str = "passed") -> Optional[Changeset]:
        cs = self.get(changeset_id)
        if not cs:
            return None
        cs.verification_status = status
        if status == "passed":
            cs.status = ChangesetStatus.VERIFIED
        cs.updated_at = time.time()
        self.store.put(self._col, cs.changeset_id, cs.to_dict())
        return cs
