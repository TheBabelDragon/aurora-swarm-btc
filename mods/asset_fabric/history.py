"""
Append-only artifact history.

Bitcoin provides the external ordering anchor.
The swarm provides replication.
Asset Fabric provides object semantics.

Events are never deleted. A reorg adds new events; it does not erase
the historical observation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from comms.layer import CommsLayer

logger = logging.getLogger("aurora.assets.history")

PUBLISHED = "PUBLISHED"
ANNOUNCED = "ANNOUNCED"
REQUESTED = "REQUESTED"
PIECE_VERIFIED = "PIECE_VERIFIED"
POSSESSION_VERIFIED = "POSSESSION_VERIFIED"
COMPLETE = "COMPLETE"
ANCHORED = "ANCHORED"
REANCHORED = "REANCHORED"

EVENT_TYPES = (
    PUBLISHED,
    ANNOUNCED,
    REQUESTED,
    PIECE_VERIFIED,
    POSSESSION_VERIFIED,
    COMPLETE,
    ANCHORED,
    REANCHORED,
)

HISTORY_PREFIX = "asset:history:"


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def evidence_hash(
    *,
    asset_id: str,
    manifest_hash: str,
    event_type: str,
    epoch: Optional[int],
    peer_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    body = {
        "asset_id": asset_id,
        "manifest_hash": manifest_hash,
        "event_type": event_type,
        "epoch": epoch,
        "peer_id": peer_id,
        "payload": payload or {},
    }
    return hashlib.sha256(_canon(body)).hexdigest()


@dataclass
class HistoryEvent:
    sequence: int
    asset_id: str
    manifest_hash: str
    event_type: str
    epoch: Optional[int]
    peer_id: str
    evidence_hash: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "asset_id": self.asset_id,
            "manifest_hash": self.manifest_hash,
            "event_type": self.event_type,
            "epoch": self.epoch,
            "peer_id": self.peer_id,
            "evidence_hash": self.evidence_hash,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HistoryEvent":
        return cls(
            sequence=int(d["sequence"]),
            asset_id=str(d["asset_id"]),
            manifest_hash=str(d.get("manifest_hash") or ""),
            event_type=str(d["event_type"]),
            epoch=d.get("epoch"),
            peer_id=str(d.get("peer_id") or ""),
            evidence_hash=str(d.get("evidence_hash") or ""),
            payload=dict(d.get("payload") or {}),
        )


class ArtifactHistory:
    def __init__(self, comms: CommsLayer):
        self.comms = comms
        self.node_id = comms.node_id

    def _key(self, asset_id: str) -> str:
        return f"{HISTORY_PREFIX}{asset_id}"

    def get(self, asset_id: str) -> List[HistoryEvent]:
        asset_id = str(asset_id).strip().lower()
        raw = self.comms.get_state(self._key(asset_id))
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            try:
                out.append(HistoryEvent.from_dict(item))
            except Exception:
                continue
        out.sort(key=lambda e: e.sequence)
        return out

    def append(
        self,
        asset_id: str,
        event_type: str,
        *,
        manifest_hash: str,
        epoch: Optional[int] = None,
        peer_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> HistoryEvent:
        asset_id = str(asset_id).strip().lower()
        event_type = str(event_type).upper()
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown history event {event_type}")
        existing = self.get(asset_id)
        seq = (existing[-1].sequence + 1) if existing else 1
        peer = peer_id or self.node_id
        eh = evidence_hash(
            asset_id=asset_id,
            manifest_hash=manifest_hash,
            event_type=event_type,
            epoch=epoch,
            peer_id=peer,
            payload=payload,
        )
        ev = HistoryEvent(
            sequence=seq,
            asset_id=asset_id,
            manifest_hash=manifest_hash,
            event_type=event_type,
            epoch=epoch,
            peer_id=peer,
            evidence_hash=eh,
            payload=dict(payload or {}),
        )
        stored = [e.to_dict() for e in existing] + [ev.to_dict()]
        self.comms.set_state(self._key(asset_id), stored, expire=0)
        return ev
