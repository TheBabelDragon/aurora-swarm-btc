"""Append-only evidence store with replication (no history rewrite)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

from .envelope import (
    EvidenceObject,
    IntegrityStatus,
    verify_integrity,
    check_schema,
)


@dataclass
class ReplicationResult:
    accepted: List[str] = field(default_factory=list)
    rejected: Dict[str, str] = field(default_factory=dict)
    duplicates: List[str] = field(default_factory=list)


class EvidenceStore:
    """In-memory append-only store of integrity-checked evidence objects."""

    def __init__(self) -> None:
        self._by_hash: Dict[str, EvidenceObject] = {}
        self._order: List[str] = []

    def __len__(self) -> int:
        return len(self._order)

    def __contains__(self, content_hash: str) -> bool:
        return content_hash in self._by_hash

    def get(self, content_hash: str) -> Optional[EvidenceObject]:
        return self._by_hash.get(content_hash)

    def __iter__(self) -> Iterator[EvidenceObject]:
        for h in self._order:
            yield self._by_hash[h]

    def append(self, obj: EvidenceObject) -> str:
        status = verify_integrity(obj)
        if status != IntegrityStatus.VALID:
            raise ValueError(f"integrity check failed: {status.value}")
        check_schema(obj)
        if obj.content_hash in self._by_hash:
            return obj.content_hash
        self._by_hash[obj.content_hash] = obj
        self._order.append(obj.content_hash)
        return obj.content_hash

    def replicate(self, objects: List[EvidenceObject]) -> ReplicationResult:
        result = ReplicationResult()
        for obj in objects:
            try:
                status = verify_integrity(obj)
                if status != IntegrityStatus.VALID:
                    result.rejected[obj.content_hash or "?"] = status.value
                    continue
                check_schema(obj)
            except ValueError as exc:
                result.rejected[obj.content_hash or "?"] = str(exc)
                continue
            if obj.content_hash in self._by_hash:
                result.duplicates.append(obj.content_hash)
                continue
            self._by_hash[obj.content_hash] = obj
            self._order.append(obj.content_hash)
            result.accepted.append(obj.content_hash)
        return result

    def export(self) -> List[dict]:
        return [self._by_hash[h].to_dict() for h in self._order]

    @classmethod
    def import_store(cls, data: List[dict]) -> "EvidenceStore":
        store = cls()
        for item in data:
            obj = EvidenceObject.from_dict(item)
            store.append(obj)
        return store

    def chain_hashes(self) -> List[str]:
        return list(self._order)
