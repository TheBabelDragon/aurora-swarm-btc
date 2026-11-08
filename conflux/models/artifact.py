"""Artifact identity and manifests.

Artifact storage and distribution authority is Asset Fabric.
Possession is not authenticity.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ArtifactRef:
    """Content-addressed reference to a published artifact."""

    artifact_id: str
    content_hash: str  # SHA-256 of payload
    name: str = ""
    media_type: str = "application/octet-stream"
    size_bytes: int = 0
    project_id: str = ""
    build_id: str = ""
    source_revision_id: str = ""
    fabric_asset_id: str = ""  # Asset Fabric identity when published
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "content_hash": self.content_hash,
            "name": self.name,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "project_id": self.project_id,
            "build_id": self.build_id,
            "source_revision_id": self.source_revision_id,
            "fabric_asset_id": self.fabric_asset_id,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ArtifactRef":
        return cls(
            artifact_id=str(d.get("artifact_id") or ""),
            content_hash=str(d.get("content_hash") or ""),
            name=str(d.get("name") or ""),
            media_type=str(d.get("media_type") or "application/octet-stream"),
            size_bytes=int(d.get("size_bytes") or 0),
            project_id=str(d.get("project_id") or ""),
            build_id=str(d.get("build_id") or ""),
            source_revision_id=str(d.get("source_revision_id") or ""),
            fabric_asset_id=str(d.get("fabric_asset_id") or ""),
            created_at=float(d.get("created_at") or 0.0),
            metadata=dict(d.get("metadata") or {}),
        )

    @staticmethod
    def from_bytes(
        data: bytes,
        *,
        name: str = "",
        media_type: str = "application/octet-stream",
        project_id: str = "",
        build_id: str = "",
        source_revision_id: str = "",
    ) -> "ArtifactRef":
        h = hashlib.sha256(data).hexdigest()
        return ArtifactRef(
            artifact_id="art_" + h[:16],
            content_hash=h,
            name=name or h[:12],
            media_type=media_type,
            size_bytes=len(data),
            project_id=project_id,
            build_id=build_id,
            source_revision_id=source_revision_id,
        )


@dataclass
class ArtifactManifest:
    """Collection of artifacts produced by a build."""

    manifest_id: str
    project_id: str
    build_id: str
    source_revision_id: str
    artifacts: List[ArtifactRef] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    content_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "manifest_id": self.manifest_id,
            "project_id": self.project_id,
            "build_id": self.build_id,
            "source_revision_id": self.source_revision_id,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "created_at": self.created_at,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ArtifactManifest":
        arts = [ArtifactRef.from_dict(a) for a in (d.get("artifacts") or [])]
        return cls(
            manifest_id=str(d.get("manifest_id") or ""),
            project_id=str(d.get("project_id") or ""),
            build_id=str(d.get("build_id") or ""),
            source_revision_id=str(d.get("source_revision_id") or ""),
            artifacts=arts,
            created_at=float(d.get("created_at") or 0.0),
            content_hash=str(d.get("content_hash") or ""),
        )

    @staticmethod
    def new(
        project_id: str,
        build_id: str,
        source_revision_id: str,
        artifacts: Optional[List[ArtifactRef]] = None,
    ) -> "ArtifactManifest":
        mid = "am_" + uuid.uuid4().hex[:12]
        m = ArtifactManifest(
            manifest_id=mid,
            project_id=project_id,
            build_id=build_id,
            source_revision_id=source_revision_id,
            artifacts=artifacts or [],
        )
        payload = {
            "project_id": project_id,
            "build_id": build_id,
            "source_revision_id": source_revision_id,
            "artifact_hashes": sorted(a.content_hash for a in m.artifacts),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        m.content_hash = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return m
