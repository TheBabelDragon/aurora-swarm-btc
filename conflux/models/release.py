"""Immutable release records.

Never mutate an existing release to represent a new release.
Corrections create new evidence / supersession records.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ReleaseStatus(str, Enum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    PROMOTED = "promoted"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


@dataclass
class Release:
    """Immutable release identity."""

    release_id: str
    project_id: str
    version: str
    source_revision_id: str
    changeset_ids: List[str] = field(default_factory=list)
    build_id: str = ""
    artifact_manifest_id: str = ""
    verification_evidence_ids: List[str] = field(default_factory=list)
    approval_evidence_ids: List[str] = field(default_factory=list)
    status: ReleaseStatus = ReleaseStatus.CANDIDATE
    promoted_at: float = 0.0
    promoted_by: str = ""
    superseded_by: str = ""
    created_at: float = field(default_factory=time.time)
    created_by: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "release_id": self.release_id,
            "project_id": self.project_id,
            "version": self.version,
            "source_revision_id": self.source_revision_id,
            "changeset_ids": list(self.changeset_ids),
            "build_id": self.build_id,
            "artifact_manifest_id": self.artifact_manifest_id,
            "verification_evidence_ids": list(self.verification_evidence_ids),
            "approval_evidence_ids": list(self.approval_evidence_ids),
            "status": self.status.value if isinstance(self.status, ReleaseStatus) else str(self.status),
            "promoted_at": self.promoted_at,
            "promoted_by": self.promoted_by,
            "superseded_by": self.superseded_by,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "metadata": dict(self.metadata),
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Release":
        status_raw = str(d.get("status") or "candidate").lower()
        try:
            status = ReleaseStatus(status_raw)
        except ValueError:
            status = ReleaseStatus.CANDIDATE
        return cls(
            release_id=str(d.get("release_id") or ""),
            project_id=str(d.get("project_id") or ""),
            version=str(d.get("version") or ""),
            source_revision_id=str(d.get("source_revision_id") or ""),
            changeset_ids=list(d.get("changeset_ids") or []),
            build_id=str(d.get("build_id") or ""),
            artifact_manifest_id=str(d.get("artifact_manifest_id") or ""),
            verification_evidence_ids=list(d.get("verification_evidence_ids") or []),
            approval_evidence_ids=list(d.get("approval_evidence_ids") or []),
            status=status,
            promoted_at=float(d.get("promoted_at") or 0.0),
            promoted_by=str(d.get("promoted_by") or ""),
            superseded_by=str(d.get("superseded_by") or ""),
            created_at=float(d.get("created_at") or 0.0),
            created_by=str(d.get("created_by") or ""),
            metadata=dict(d.get("metadata") or {}),
            content_hash=str(d.get("content_hash") or ""),
        )

    @staticmethod
    def new(
        project_id: str,
        version: str,
        source_revision_id: str,
        *,
        build_id: str = "",
        artifact_manifest_id: str = "",
        changeset_ids: Optional[List[str]] = None,
        created_by: str = "",
    ) -> "Release":
        rid = "rel_" + uuid.uuid4().hex[:12]
        r = Release(
            release_id=rid,
            project_id=project_id,
            version=version,
            source_revision_id=source_revision_id,
            build_id=build_id,
            artifact_manifest_id=artifact_manifest_id,
            changeset_ids=changeset_ids or [],
            created_by=created_by,
            status=ReleaseStatus.CANDIDATE,
        )
        r.content_hash = Release._hash(r)
        return r

    @staticmethod
    def _hash(r: "Release") -> str:
        payload = {
            "release_id": r.release_id,
            "project_id": r.project_id,
            "version": r.version,
            "source_revision_id": r.source_revision_id,
            "build_id": r.build_id,
            "artifact_manifest_id": r.artifact_manifest_id,
            "changeset_ids": sorted(r.changeset_ids),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
