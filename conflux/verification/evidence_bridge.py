"""Bridge Conflux lifecycle events into mods.evidence_integrity.

IMPORTANT: EvidenceStore is currently in-memory. This bridge does not claim
durable or distributed evidence storage. A persistence adapter boundary is
exposed via export/import for future replication backends.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("conflux.evidence")


class EvidenceBridge:
    """Append-only evidence publisher for Conflux events."""

    def __init__(self, *, node_id: str = "conflux") -> None:
        self.node_id = node_id
        self._store = None
        self._last_hash: Optional[str] = None
        self._init_store()

    def _init_store(self) -> None:
        try:
            from mods.evidence_integrity import EvidenceStore

            self._store = EvidenceStore()
        except Exception as e:
            logger.warning("EvidenceStore unavailable: %s", e)
            self._store = None

    @property
    def available(self) -> bool:
        return self._store is not None

    def record(
        self,
        event_type: str,
        *,
        entity_id: str,
        project_id: str = "",
        source_revision_id: str = "",
        build_id: str = "",
        release_id: str = "",
        deployment_id: str = "",
        actor_id: str = "",
        outcome: str = "",
        parent_hashes: Optional[List[str]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Create and append an evidence object. Returns content_hash or None."""
        if self._store is None:
            return None

        try:
            from mods.evidence_integrity import build_evidence_object, verify_integrity
        except Exception as e:
            logger.warning("evidence_integrity import failed: %s", e)
            return None

        payload: Dict[str, Any] = {
            "subsystem": "conflux",
            "event_type": event_type,
            "entity_id": entity_id,
            "project_id": project_id,
            "source_revision_id": source_revision_id,
            "build_id": build_id,
            "release_id": release_id,
            "deployment_id": deployment_id,
            "actor_id": actor_id,
            "outcome": outcome,
            "observed_at": time.time(),
        }
        if extra:
            payload["extra"] = extra

        parents = list(parent_hashes or [])
        if self._last_hash and self._last_hash not in parents:
            parents.append(self._last_hash)

        try:
            obj = build_evidence_object(
                payload,
                parent_hashes=parents,
                node_id=self.node_id,
                extras={"conflux_event": event_type},
            )
            status = verify_integrity(obj)
            if status.value != "VALID":
                logger.warning("evidence integrity failed: %s", status)
                return None
            h = self._store.append(obj)
            self._last_hash = h
            return h
        except Exception as e:
            logger.warning("evidence record failed: %s", e)
            return None

    def get(self, content_hash: str) -> Optional[dict]:
        if self._store is None:
            return None
        obj = self._store.get(content_hash)
        return obj.to_dict() if obj else None

    def export(self) -> List[dict]:
        """Persistence boundary: export for external durable backends."""
        if self._store is None:
            return []
        return self._store.export()

    def chain_hashes(self) -> List[str]:
        if self._store is None:
            return []
        return self._store.chain_hashes()

    def status(self) -> dict:
        return {
            "available": self.available,
            "backend": "in_memory",
            "durable": False,
            "count": len(self._store) if self._store else 0,
            "note": "EvidenceStore is process-local; use export() for persistence adapters",
        }
