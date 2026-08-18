"""AnchorRecord — mesh-visible attestation state for an asset."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class AnchorRecord:
    asset_id: str
    commitment: str
    status: str = "recorded"          # recorded | pending_broadcast | confirmed | failed
    created_at: float = field(default_factory=time.time)
    created_by: str = ""
    txid: Optional[str] = None        # filled when a real broadcast succeeds
    network: str = "bitcoin"          # future: signet / testnet / mainnet
    method: str = "mesh_record"       # mesh_record | op_return | batch | external
    note: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

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
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AnchorRecord":
        return cls(
            asset_id=str(d["asset_id"]),
            commitment=str(d["commitment"]),
            status=str(d.get("status", "recorded")),
            created_at=float(d.get("created_at", time.time())),
            created_by=str(d.get("created_by", "")),
            txid=d.get("txid"),
            network=str(d.get("network", "bitcoin")),
            method=str(d.get("method", "mesh_record")),
            note=str(d.get("note", "")),
            meta=dict(d.get("meta") or {}),
        )
