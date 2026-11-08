"""Evidence and provenance records.

Integrates with mods/evidence_integrity.
Corrections create new evidence objects; history is never rewritten.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvidenceRef:
    """Pointer to an evidence object (local or evidence_integrity store)."""

    evidence_id: str
    kind: str  # build | approval | verification | deployment | audit
    content_hash: str = ""
    store: str = "conflux"  # conflux | evidence_integrity
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "content_hash": self.content_hash,
            "store": self.store,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EvidenceRef":
        return cls(
            evidence_id=str(d.get("evidence_id") or ""),
            kind=str(d.get("kind") or ""),
            content_hash=str(d.get("content_hash") or ""),
            store=str(d.get("store") or "conflux"),
            created_at=float(d.get("created_at") or 0.0),
            metadata=dict(d.get("metadata") or {}),
        )


@dataclass
class ProvenanceRecord:
    """End-to-end provenance for a build or release."""

    provenance_id: str
    project_id: str
    source_revision_id: str = ""
    changeset_ids: List[str] = field(default_factory=list)
    build_id: str = ""
    artifact_ids: List[str] = field(default_factory=list)
    release_id: str = ""
    deployment_id: str = ""
    evidence_refs: List[EvidenceRef] = field(default_factory=list)
    environment: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    content_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "provenance_id": self.provenance_id,
            "project_id": self.project_id,
            "source_revision_id": self.source_revision_id,
            "changeset_ids": list(self.changeset_ids),
            "build_id": self.build_id,
            "artifact_ids": list(self.artifact_ids),
            "release_id": self.release_id,
            "deployment_id": self.deployment_id,
            "evidence_refs": [e.to_dict() for e in self.evidence_refs],
            "environment": dict(self.environment),
            "created_at": self.created_at,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProvenanceRecord":
        refs = [EvidenceRef.from_dict(e) for e in (d.get("evidence_refs") or [])]
        return cls(
            provenance_id=str(d.get("provenance_id") or ""),
            project_id=str(d.get("project_id") or ""),
            source_revision_id=str(d.get("source_revision_id") or ""),
            changeset_ids=list(d.get("changeset_ids") or []),
            build_id=str(d.get("build_id") or ""),
            artifact_ids=list(d.get("artifact_ids") or []),
            release_id=str(d.get("release_id") or ""),
            deployment_id=str(d.get("deployment_id") or ""),
            evidence_refs=refs,
            environment=dict(d.get("environment") or {}),
            created_at=float(d.get("created_at") or 0.0),
            content_hash=str(d.get("content_hash") or ""),
        )

    @staticmethod
    def new(project_id: str, **kwargs: Any) -> "ProvenanceRecord":
        p = ProvenanceRecord(
            provenance_id="prov_" + uuid.uuid4().hex[:12],
            project_id=project_id,
            **{k: v for k, v in kwargs.items() if k in {
                "source_revision_id", "changeset_ids", "build_id",
                "artifact_ids", "release_id", "deployment_id", "evidence_refs", "environment",
            }}
        )
        payload = {
            "project_id": p.project_id,
            "source_revision_id": p.source_revision_id,
            "build_id": p.build_id,
            "release_id": p.release_id,
            "artifact_ids": sorted(p.artifact_ids),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        p.content_hash = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return p
