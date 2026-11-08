"""Agent-native changeset model.

Never silently resolve semantic conflicts.
Never automatically promote an unverified changeset.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ChangesetStatus(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    CONFLICTING = "conflicting"
    RECONCILED = "reconciled"
    VERIFIED = "verified"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass
class FileChange:
    path: str
    change_type: str  # add | modify | modify | rename
    old_path: str = ""
    content_hash_before: str = ""
    content_hash_after: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "change_type": self.change_type,
            "old_path": self.old_path,
            "content_hash_before": self.content_hash_before,
            "content_hash_after": self.content_hash_after,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FileChange":
        return cls(
            path=str(d.get("path") or ""),
            change_type=str(d.get("change_type") or "modify"),
            old_path=str(d.get("old_path") or ""),
            content_hash_before=str(d.get("content_hash_before") or ""),
            content_hash_after=str(d.get("content_hash_after") or ""),
        )


@dataclass
class Changeset:
    """A proposed set of changes against a base revision."""

    changeset_id: str
    project_id: str
    source_id: str
    base_revision_id: str
    source_revision_id: str = ""  # tip after apply if known
    author: str = ""
    agent_id: str = ""
    intent: str = ""
    files: List[FileChange] = field(default_factory=list)
    parent_changeset_ids: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    status: ChangesetStatus = ChangesetStatus.DRAFT
    verification_status: str = "pending"  # pending | passed | failed | advisory
    approval_status: str = "pending"  # pending | approved | rejected
    approved_by: str = ""
    approved_at: float = 0.0
    conflict_paths: List[str] = field(default_factory=list)
    provenance_refs: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "changeset_id": self.changeset_id,
            "project_id": self.project_id,
            "source_id": self.source_id,
            "base_revision_id": self.base_revision_id,
            "source_revision_id": self.source_revision_id,
            "author": self.author,
            "agent_id": self.agent_id,
            "intent": self.intent,
            "files": [f.to_dict() for f in self.files],
            "parent_changeset_ids": list(self.parent_changeset_ids),
            "depends_on": list(self.depends_on),
            "status": self.status.value if isinstance(self.status, ChangesetStatus) else str(self.status),
            "verification_status": self.verification_status,
            "approval_status": self.approval_status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "conflict_paths": list(self.conflict_paths),
            "provenance_refs": list(self.provenance_refs),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Changeset":
        status_raw = str(d.get("status") or "draft").lower()
        try:
            status = ChangesetStatus(status_raw)
        except ValueError:
            status = ChangesetStatus.DRAFT
        files = [FileChange.from_dict(f) for f in (d.get("files") or [])]
        return cls(
            changeset_id=str(d.get("changeset_id") or ""),
            project_id=str(d.get("project_id") or ""),
            source_id=str(d.get("source_id") or ""),
            base_revision_id=str(d.get("base_revision_id") or ""),
            source_revision_id=str(d.get("source_revision_id") or ""),
            author=str(d.get("author") or ""),
            agent_id=str(d.get("agent_id") or ""),
            intent=str(d.get("intent") or ""),
            files=files,
            parent_changeset_ids=list(d.get("parent_changeset_ids") or []),
            depends_on=list(d.get("depends_on") or []),
            status=status,
            verification_status=str(d.get("verification_status") or "pending"),
            approval_status=str(d.get("approval_status") or "pending"),
            approved_by=str(d.get("approved_by") or ""),
            approved_at=float(d.get("approved_at") or 0.0),
            conflict_paths=list(d.get("conflict_paths") or []),
            provenance_refs=list(d.get("provenance_refs") or []),
            created_at=float(d.get("created_at") or 0.0),
            updated_at=float(d.get("updated_at") or 0.0),
            metadata=dict(d.get("metadata") or {}),
            content_hash=str(d.get("content_hash") or ""),
        )

    @staticmethod
    def new(
        project_id: str,
        source_id: str,
        base_revision_id: str,
        *,
        author: str = "",
        agent_id: str = "",
        intent: str = "",
        files: Optional[List[FileChange]] = None,
    ) -> "Changeset":
        cid = "cs_" + uuid.uuid4().hex[:12]
        cs = Changeset(
            changeset_id=cid,
            project_id=project_id,
            source_id=source_id,
            base_revision_id=base_revision_id,
            author=author,
            agent_id=agent_id,
            intent=intent,
            files=files or [],
            status=ChangesetStatus.DRAFT,
        )
        cs.content_hash = Changeset._hash(cs)
        return cs

    @staticmethod
    def _hash(cs: "Changeset") -> str:
        payload = {
            "changeset_id": cs.changeset_id,
            "project_id": cs.project_id,
            "source_id": cs.source_id,
            "base_revision_id": cs.base_revision_id,
            "files": sorted(
                [{"path": f.path, "change_type": f.change_type, "after": f.content_hash_after} for f in cs.files],
                key=lambda x: x["path"],
            ),
            "intent": cs.intent,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
