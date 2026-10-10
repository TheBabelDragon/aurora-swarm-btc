"""Content-addressed evidence objects for Aurora Mesh."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


SCHEMA_ID = "aurora.mesh.evidence"
SCHEMA_VERSION = "0.1.0"


class IntegrityStatus(str, Enum):
    VALID = "VALID"
    HASH_MISMATCH = "HASH_MISMATCH"
    MISSING_PAYLOAD = "MISSING_PAYLOAD"
    SCHEMA_INCOMPATIBLE = "SCHEMA_INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


def _canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def content_hash(payload: Dict[str, Any]) -> str:
    """SHA-256 hex of canonical payload. Content hash IS identity."""
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


@dataclass
class EvidenceObject:
    """Immutable evidence object for mesh distribution."""

    content_hash: str
    payload: Dict[str, Any]
    schema_id: str = SCHEMA_ID
    schema_version: str = SCHEMA_VERSION
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    parent_hashes: List[str] = field(default_factory=list)
    node_id: str = ""
    sequence: Optional[int] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content_hash": self.content_hash,
            "payload": dict(self.payload),
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "evidence_refs": list(self.evidence_refs),
            "parent_hashes": list(self.parent_hashes),
            "node_id": self.node_id,
            "sequence": self.sequence,
            "extras": dict(self.extras) if self.extras else {},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceObject":
        return cls(
            content_hash=str(data.get("content_hash") or ""),
            payload=dict(data.get("payload") or {}),
            schema_id=str(data.get("schema_id") or SCHEMA_ID),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
            evidence_refs=list(data.get("evidence_refs") or []),
            parent_hashes=list(data.get("parent_hashes") or []),
            node_id=str(data.get("node_id") or ""),
            sequence=data.get("sequence"),
            extras=dict(data.get("extras") or {}),
        )


def build_evidence_object(
    payload: Dict[str, Any],
    *,
    evidence_refs: Optional[List[Dict[str, Any]]] = None,
    parent_hashes: Optional[List[str]] = None,
    node_id: str = "",
    sequence: Optional[int] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> EvidenceObject:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    if not payload:
        raise ValueError("payload must not be empty")
    h = content_hash(payload)
    return EvidenceObject(
        content_hash=h,
        payload=dict(payload),
        evidence_refs=list(evidence_refs or []),
        parent_hashes=list(parent_hashes or []),
        node_id=node_id,
        sequence=sequence,
        extras=dict(extras or {}),
    )


def verify_integrity(obj: EvidenceObject) -> IntegrityStatus:
    if not obj.payload:
        return IntegrityStatus.MISSING_PAYLOAD
    expected = content_hash(obj.payload)
    if expected != obj.content_hash:
        return IntegrityStatus.HASH_MISMATCH
    return IntegrityStatus.VALID


def check_schema(
    obj: EvidenceObject,
    *,
    expected_schema_id: str = SCHEMA_ID,
    expected_major: int = 0,
) -> None:
    if obj.schema_id and obj.schema_id != expected_schema_id:
        raise ValueError(
            f"incompatible schema_id: {obj.schema_id!r} "
            f"(expected {expected_schema_id!r})"
        )
    try:
        major = int(str(obj.schema_version).split(".")[0])
    except ValueError as exc:
        raise ValueError(
            f"unparseable schema_version: {obj.schema_version!r}"
        ) from exc
    if major != expected_major:
        raise ValueError(
            f"incompatible schema major version: {obj.schema_version} "
            f"(supported major={expected_major})"
        )
