"""Project identity and registered source references."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SourceRef:
    """A registered source location for a project.

    Identity is content-addressed over (kind, remote_url, local_path).
    """

    source_id: str
    kind: str  # "git" | future native kinds
    remote_url: str = ""
    local_path: str = ""
    default_branch: str = "main"
    registered_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "kind": self.kind,
            "remote_url": self.remote_url,
            "local_path": self.local_path,
            "default_branch": self.default_branch,
            "registered_at": self.registered_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourceRef":
        return cls(
            source_id=str(d.get("source_id") or ""),
            kind=str(d.get("kind") or "git"),
            remote_url=str(d.get("remote_url") or ""),
            local_path=str(d.get("local_path") or ""),
            default_branch=str(d.get("default_branch") or "main"),
            registered_at=float(d.get("registered_at") or 0.0),
            metadata=dict(d.get("metadata") or {}),
        )

    @staticmethod
    def make_id(kind: str, remote_url: str, local_path: str) -> str:
        payload = json.dumps(
            {"kind": kind, "remote_url": remote_url or "", "local_path": local_path or ""},
            sort_keys=True,
            separators=(",", ":"),
        )
        return "src_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class Project:
    """A Conflux project — the top-level lifecycle container."""

    project_id: str
    name: str
    description: str = ""
    sources: List[SourceRef] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    created_by: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "sources": [s.to_dict() for s in self.sources],
            "created_at": self.created_at,
            "created_by": self.created_by,
            "metadata": dict(self.metadata),
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        sources = [SourceRef.from_dict(s) for s in (d.get("sources") or [])]
        return cls(
            project_id=str(d.get("project_id") or ""),
            name=str(d.get("name") or ""),
            description=str(d.get("description") or ""),
            sources=sources,
            created_at=float(d.get("created_at") or 0.0),
            created_by=str(d.get("created_by") or ""),
            metadata=dict(d.get("metadata") or {}),
            content_hash=str(d.get("content_hash") or ""),
        )

    @staticmethod
    def new(name: str, *, description: str = "", created_by: str = "") -> "Project":
        pid = "prj_" + uuid.uuid4().hex[:12]
        p = Project(project_id=pid, name=name, description=description, created_by=created_by)
        p.content_hash = Project._hash(p)
        return p

    @staticmethod
    def _hash(p: "Project") -> str:
        payload = {
            "project_id": p.project_id,
            "name": p.name,
            "description": p.description,
            "source_ids": sorted(s.source_id for s in p.sources),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
