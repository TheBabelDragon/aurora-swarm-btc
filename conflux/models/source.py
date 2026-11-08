"""Source revision and immutable snapshot identities."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SourceRevision:
    """A point in source history (Git commit or future native revision)."""

    revision_id: str  # content-addressed or Git SHA
    source_id: str
    project_id: str
    kind: str = "git"  # git | native
    branch: str = ""
    tags: List[str] = field(default_factory=list)
    message: str = ""
    author: str = ""
    committed_at: float = 0.0
    parent_ids: List[str] = field(default_factory=list)
    tree_hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "revision_id": self.revision_id,
            "source_id": self.source_id,
            "project_id": self.project_id,
            "kind": self.kind,
            "branch": self.branch,
            "tags": list(self.tags),
            "message": self.message,
            "author": self.author,
            "committed_at": self.committed_at,
            "parent_ids": list(self.parent_ids),
            "tree_hash": self.tree_hash,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourceRevision":
        return cls(
            revision_id=str(d.get("revision_id") or ""),
            source_id=str(d.get("source_id") or ""),
            project_id=str(d.get("project_id") or ""),
            kind=str(d.get("kind") or "git"),
            branch=str(d.get("branch") or ""),
            tags=list(d.get("tags") or []),
            message=str(d.get("message") or ""),
            author=str(d.get("author") or ""),
            committed_at=float(d.get("committed_at") or 0.0),
            parent_ids=list(d.get("parent_ids") or []),
            tree_hash=str(d.get("tree_hash") or ""),
            metadata=dict(d.get("metadata") or {}),
        )


@dataclass
class SourceSnapshot:
    """Immutable capture of a source tree at a revision."""

    snapshot_id: str
    revision_id: str
    source_id: str
    project_id: str
    created_at: float = field(default_factory=time.time)
    file_count: int = 0
    content_hash: str = ""  # overall tree / archive hash
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "revision_id": self.revision_id,
            "source_id": self.source_id,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "file_count": self.file_count,
            "content_hash": self.content_hash,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourceSnapshot":
        return cls(
            snapshot_id=str(d.get("snapshot_id") or ""),
            revision_id=str(d.get("revision_id") or ""),
            source_id=str(d.get("source_id") or ""),
            project_id=str(d.get("project_id") or ""),
            created_at=float(d.get("created_at") or 0.0),
            file_count=int(d.get("file_count") or 0),
            content_hash=str(d.get("content_hash") or ""),
            metadata=dict(d.get("metadata") or {}),
        )
