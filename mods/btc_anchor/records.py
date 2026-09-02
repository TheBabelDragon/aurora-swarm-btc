"""AnchorRecord — mesh-visible attestation state for an asset.

`asset_id` is the artifact identity.
`anchor_id` is a temporal observation of that identity.
A locally observed txid is not a confirmed anchor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .lifecycle import (
    COMMITMENT_PENDING,
    default_confirmation_depth,
    normalize_status,
)


@dataclass
class AnchorRecord:
    asset_id: str
    commitment: str
    status: str = COMMITMENT_PENDING
    created_at: float = 0.0  # informational observation metadata; not the epoch
    created_by: str = ""
    txid: Optional[str] = None
    network: str = "bitcoin"
    method: str = "mesh_record"  # mesh_record | op_return | batch | external | simulated
    note: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    # Artifact-clock fields
    anchor_id: Optional[str] = None
    manifest_hash: str = ""
    artifact_epoch: Optional[int] = None
    commitment_version: int = 1
    btc_height: Optional[int] = None
    btc_block_hash: Optional[str] = None
    btc_work: Optional[str] = None
    included_at: Optional[int] = None  # block timestamp (informational)
    confirmations: int = 0
    confirmation_depth: int = field(default_factory=default_confirmation_depth)
    canonical: bool = False
    observed: bool = True  # we keep the observation even after a reorg

    def __post_init__(self):
        self.status = normalize_status(self.status)
        if self.confirmation_depth < 1:
            self.confirmation_depth = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "commitment": self.commitment,
            "status": self.status,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "txid": self.txid,
            "network": self.network,
            "method": self.method,
            "note": self.note,
            "meta": dict(self.meta),
            "anchor_id": self.anchor_id,
            "manifest_hash": self.manifest_hash,
            "artifact_epoch": self.artifact_epoch,
            "commitment_version": self.commitment_version,
            "btc_height": self.btc_height,
            "btc_block_hash": self.btc_block_hash,
            "btc_work": self.btc_work,
            "included_at": self.included_at,
            "confirmations": self.confirmations,
            "confirmation_depth": self.confirmation_depth,
            "canonical": self.canonical,
            "observed": self.observed,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AnchorRecord":
        return cls(
            asset_id=str(d["asset_id"]),
            commitment=str(d["commitment"]),
            status=normalize_status(d.get("status")),
            created_at=float(d.get("created_at") or 0.0),
            created_by=str(d.get("created_by", "")),
            txid=d.get("txid"),
            network=str(d.get("network", "bitcoin")),
            method=str(d.get("method", "mesh_record")),
            note=str(d.get("note", "")),
            meta=dict(d.get("meta") or {}),
            anchor_id=d.get("anchor_id"),
            manifest_hash=str(d.get("manifest_hash") or ""),
            artifact_epoch=d.get("artifact_epoch"),
            commitment_version=int(d.get("commitment_version") or 1),
            btc_height=d.get("btc_height"),
            btc_block_hash=d.get("btc_block_hash"),
            btc_work=d.get("btc_work"),
            included_at=d.get("included_at"),
            confirmations=int(d.get("confirmations") or 0),
            confirmation_depth=int(d.get("confirmation_depth") or default_confirmation_depth()),
            canonical=bool(d.get("canonical", False)),
            observed=bool(d.get("observed", True)),
        )
