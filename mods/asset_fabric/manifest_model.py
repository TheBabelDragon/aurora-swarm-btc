"""
AssetManifest — immutable content-addressed description of a swarm asset.

This is the durable object. Everything else (models, datasets, calibration,
voxel maps, checkpoints, firmware, sensor captures) is just an asset with
a type and a schema version.

The artifact’s content hash remains the artifact identity.
The Bitcoin anchor identifies a temporal observation of that identity.

    asset_id  !=  anchor_id
    same asset + different anchor  =  same artifact, different temporal observation

Temporal metadata is optional and is NEVER part of the identity hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def identity_payload(manifest_like: Dict[str, Any]) -> Dict[str, Any]:
    """Content-critical fields. Temporal metadata is excluded."""
    return {
        "asset_id": manifest_like.get("asset_id") or manifest_like.get("infohash"),
        "content_hash": manifest_like.get("content_hash") or manifest_like.get("asset_id"),
        "size": manifest_like.get("size"),
        "piece_size": manifest_like.get("piece_size"),
        "piece_hashes": list(manifest_like.get("piece_hashes") or []),
        "asset_type": manifest_like.get("asset_type", "blob"),
        "schema_version": manifest_like.get("schema_version", "1"),
    }


def compute_identity_hash(manifest_like: Dict[str, Any]) -> str:
    return hashlib.sha256(_canon(identity_payload(manifest_like))).hexdigest()


def asset_id_from_piece_hashes(piece_hashes: List[str]) -> str:
    """Same identity function the torrent transport uses."""
    return hashlib.sha256("".join(piece_hashes).encode()).hexdigest()[:40]


@dataclass(frozen=True)
class AssetManifest:
    """Immutable content-addressed asset descriptor."""

    asset_id: str                     # usually the content hash / infohash
    content_hash: str                 # full integrity hash of the complete object
    size: int
    piece_size: int
    piece_hashes: List[str]
    name: str = ""
    asset_type: str = "blob"          # model | dataset | calibration | map | checkpoint | firmware | blob
    schema_version: str = "1"
    created_by: str = ""
    creation_epoch: float = 0.0       # observational local metadata; NOT the Bitcoin epoch
    provenance: Dict[str, Any] = field(default_factory=dict)
    temporal: Optional[Dict[str, Any]] = None  # optional observation of a BTC clock

    def identity_fields(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "content_hash": self.content_hash,
            "size": self.size,
            "piece_size": self.piece_size,
            "piece_hashes": list(self.piece_hashes),
            "asset_type": self.asset_type,
            "schema_version": self.schema_version,
        }

    def identity_hash(self) -> str:
        """Stable hash of content identity. Independent of any Bitcoin anchor."""
        return compute_identity_hash(self.identity_fields())

    def with_temporal(self, temporal: Optional[Dict[str, Any]]) -> "AssetManifest":
        """Return a copy with updated temporal observation. Identity is unchanged."""
        return AssetManifest(
            asset_id=self.asset_id,
            content_hash=self.content_hash,
            size=self.size,
            piece_size=self.piece_size,
            piece_hashes=list(self.piece_hashes),
            name=self.name,
            asset_type=self.asset_type,
            schema_version=self.schema_version,
            created_by=self.created_by,
            creation_epoch=self.creation_epoch,
            provenance=dict(self.provenance),
            temporal=dict(temporal) if temporal else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "asset_id": self.asset_id,
            "content_hash": self.content_hash,
            "size": self.size,
            "piece_size": self.piece_size,
            "piece_hashes": list(self.piece_hashes),
            "name": self.name,
            "asset_type": self.asset_type,
            "schema_version": self.schema_version,
            "created_by": self.created_by,
            "creation_epoch": self.creation_epoch,
            "provenance": dict(self.provenance),
            "num_pieces": len(self.piece_hashes),
            "manifest_hash": self.identity_hash(),
        }
        if self.temporal:
            d["temporal"] = dict(self.temporal)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AssetManifest":
        return cls(
            asset_id=str(d["asset_id"]),
            content_hash=str(d.get("content_hash") or d["asset_id"]),
            size=int(d["size"]),
            piece_size=int(d["piece_size"]),
            piece_hashes=list(d["piece_hashes"]),
            name=str(d.get("name", "")),
            asset_type=str(d.get("asset_type", "blob")),
            schema_version=str(d.get("schema_version", "1")),
            created_by=str(d.get("created_by", "")),
            creation_epoch=float(d.get("creation_epoch") or 0.0),
            provenance=dict(d.get("provenance") or {}),
            temporal=dict(d["temporal"]) if d.get("temporal") else None,
        )

    @classmethod
    def from_payload(
        cls,
        data: bytes,
        *,
        name: str = "asset",
        piece_size: int = 16 * 1024,
        asset_type: str = "blob",
        created_by: str = "",
        provenance: Optional[Dict[str, Any]] = None,
    ) -> "AssetManifest":
        """Construct a content-addressed manifest without the torrent transport."""
        if not data:
            raise ValueError("empty payload")
        piece_size = max(16, int(piece_size))
        piece_hashes: List[str] = []
        for i in range(0, len(data), piece_size):
            chunk = data[i : i + piece_size]
            piece_hashes.append(hashlib.sha256(chunk).hexdigest())
        asset_id = asset_id_from_piece_hashes(piece_hashes)
        return cls(
            asset_id=asset_id,
            content_hash=asset_id,
            size=len(data),
            piece_size=piece_size,
            piece_hashes=piece_hashes,
            name=name,
            asset_type=asset_type,
            created_by=created_by,
            creation_epoch=0.0,
            provenance=provenance or {},
        )

    @classmethod
    def from_torrent_meta(cls, meta, asset_type: str = "blob", provenance: Optional[Dict] = None) -> "AssetManifest":
        """Bridge from the current torrent TorrentMeta into the durable AssetManifest."""
        return cls(
            asset_id=meta.infohash,
            content_hash=meta.infohash,  # current transport uses infohash as primary id
            size=meta.size,
            piece_size=meta.piece_size,
            piece_hashes=list(meta.piece_hashes),
            name=meta.name,
            asset_type=asset_type,
            created_by=meta.created_by,
            creation_epoch=float(getattr(meta, "created_at", 0.0) or 0.0),
            provenance=provenance or {},
        )

    def fingerprint(self) -> str:
        """Stable short fingerprint for logs / UI."""
        return self.asset_id[:12]
