"""Deterministic build manifests and execution records.

Runners are isolated and disabled by default.
Do not execute arbitrary repository code in the dashboard process.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class BuildStatus(str, Enum):
    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass
class BuildManifest:
    """Reproducible description of a build."""

    manifest_id: str
    project_id: str
    source_revision_id: str
    changeset_ids: List[str] = field(default_factory=list)
    instructions: List[str] = field(default_factory=list)
    toolchain: Dict[str, str] = field(default_factory=dict)
    dependency_lock: Dict[str, str] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)
    input_artifact_ids: List[str] = field(default_factory=list)
    expected_outputs: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    content_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "manifest_id": self.manifest_id,
            "project_id": self.project_id,
            "source_revision_id": self.source_revision_id,
            "changeset_ids": list(self.changeset_ids),
            "instructions": list(self.instructions),
            "toolchain": dict(self.toolchain),
            "dependency_lock": dict(self.dependency_lock),
            "environment": dict(self.environment),
            "input_artifact_ids": list(self.input_artifact_ids),
            "expected_outputs": list(self.expected_outputs),
            "created_at": self.created_at,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BuildManifest":
        return cls(
            manifest_id=str(d.get("manifest_id") or ""),
            project_id=str(d.get("project_id") or ""),
            source_revision_id=str(d.get("source_revision_id") or ""),
            changeset_ids=list(d.get("changeset_ids") or []),
            instructions=list(d.get("instructions") or []),
            toolchain=dict(d.get("toolchain") or {}),
            dependency_lock=dict(d.get("dependency_lock") or {}),
            environment=dict(d.get("environment") or {}),
            input_artifact_ids=list(d.get("input_artifact_ids") or []),
            expected_outputs=list(d.get("expected_outputs") or []),
            created_at=float(d.get("created_at") or 0.0),
            content_hash=str(d.get("content_hash") or ""),
        )

    @staticmethod
    def new(
        project_id: str,
        source_revision_id: str,
        *,
        changeset_ids: Optional[List[str]] = None,
        instructions: Optional[List[str]] = None,
        toolchain: Optional[Dict[str, str]] = None,
    ) -> "BuildManifest":
        mid = "bm_" + uuid.uuid4().hex[:12]
        m = BuildManifest(
            manifest_id=mid,
            project_id=project_id,
            source_revision_id=source_revision_id,
            changeset_ids=changeset_ids or [],
            instructions=instructions or [],
            toolchain=toolchain or {},
        )
        m.content_hash = BuildManifest._hash(m)
        return m

    @staticmethod
    def _hash(m: "BuildManifest") -> str:
        payload = {
            "project_id": m.project_id,
            "source_revision_id": m.source_revision_id,
            "changeset_ids": sorted(m.changeset_ids),
            "instructions": m.instructions,
            "toolchain": m.toolchain,
            "dependency_lock": m.dependency_lock,
            "environment": m.environment,
            "input_artifact_ids": sorted(m.input_artifact_ids),
            "expected_outputs": sorted(m.expected_outputs),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class BuildRecord:
    """Result of a build execution against a manifest."""

    build_id: str
    manifest_id: str
    project_id: str
    status: BuildStatus = BuildStatus.PLANNED
    started_at: float = 0.0
    finished_at: float = 0.0
    execution_id: str = ""
    output_artifact_ids: List[str] = field(default_factory=list)
    logs_ref: str = ""
    error: str = ""
    verification_results: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "build_id": self.build_id,
            "manifest_id": self.manifest_id,
            "project_id": self.project_id,
            "status": self.status.value if isinstance(self.status, BuildStatus) else str(self.status),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "execution_id": self.execution_id,
            "output_artifact_ids": list(self.output_artifact_ids),
            "logs_ref": self.logs_ref,
            "error": self.error,
            "verification_results": dict(self.verification_results),
            "evidence_refs": list(self.evidence_refs),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BuildRecord":
        status_raw = str(d.get("status") or "planned").lower()
        try:
            status = BuildStatus(status_raw)
        except ValueError:
            status = BuildStatus.PLANNED
        return cls(
            build_id=str(d.get("build_id") or ""),
            manifest_id=str(d.get("manifest_id") or ""),
            project_id=str(d.get("project_id") or ""),
            status=status,
            started_at=float(d.get("started_at") or 0.0),
            finished_at=float(d.get("finished_at") or 0.0),
            execution_id=str(d.get("execution_id") or ""),
            output_artifact_ids=list(d.get("output_artifact_ids") or []),
            logs_ref=str(d.get("logs_ref") or ""),
            error=str(d.get("error") or ""),
            verification_results=dict(d.get("verification_results") or {}),
            evidence_refs=list(d.get("evidence_refs") or []),
            created_at=float(d.get("created_at") or 0.0),
            metadata=dict(d.get("metadata") or {}),
        )

    @staticmethod
    def new(manifest_id: str, project_id: str) -> "BuildRecord":
        return BuildRecord(
            build_id="bld_" + uuid.uuid4().hex[:12],
            manifest_id=manifest_id,
            project_id=project_id,
            status=BuildStatus.PLANNED,
        )
