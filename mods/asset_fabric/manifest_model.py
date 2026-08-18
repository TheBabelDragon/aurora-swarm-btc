"""
AssetManifest — immutable content-addressed description of a swarm asset.

This is the durable object. Everything else (models, datasets, calibration,
voxel maps, checkpoints, firmware, sensor captures) is just an asset with
a type and a schema version.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    creation_epoch: float = field(default_factory=time.time)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
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
        }

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
            creation_epoch=float(d.get("creation_epoch", time.time())),
            provenance=dict(d.get("provenance") or {}),
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
            creation_epoch=getattr(meta, "created_at", time.time()),
            provenance=provenance or {},
        )

    def fingerprint(self) -> str:
        """Stable short fingerprint for logs / UI."""
        return self.asset_id[:12]
