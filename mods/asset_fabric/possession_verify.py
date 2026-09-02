"""
Claimed vs verified possession.

Claims are cheap. Verification is a challenge: produce bytes + proof.
Only verified possession evidence is recorded against an epoch.

A peer's claim is never historical truth.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .merkle_pieces import merkle_proof, verify_piece


@dataclass
class PossessionClaim:
    asset_id: str
    node_id: str
    piece_bitmap: Set[int] = field(default_factory=set)
    epoch: Optional[int] = None  # Bitcoin epoch if known; never wall-clock
    claimed_at: float = field(default_factory=time.time)  # observational
    manifest_hash: str = ""
    anchor_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "node_id": self.node_id,
            "pieces": sorted(self.piece_bitmap),
            "epoch": self.epoch,
            "claimed_at": self.claimed_at,
            "manifest_hash": self.manifest_hash,
            "anchor_id": self.anchor_id,
            "kind": "claimed",
        }


@dataclass
class VerifiedPossession:
    asset_id: str
    node_id: str
    verified_pieces: Set[int] = field(default_factory=set)
    last_challenge_ok: float = 0.0  # observational
    manifest_hash: str = ""
    total_pieces: int = 0
    epoch: Optional[int] = None
    anchor_id: Optional[str] = None
    possession_state: str = "partial"  # none | partial | complete

    def refresh_state(self):
        if self.total_pieces > 0 and len(self.verified_pieces) >= self.total_pieces:
            self.possession_state = "complete"
        elif self.verified_pieces:
            self.possession_state = "partial"
        else:
            self.possession_state = "none"

    def to_dict(self) -> Dict[str, Any]:
        self.refresh_state()
        return {
            "asset_id": self.asset_id,
            "manifest_hash": self.manifest_hash,
            "peer_id": self.node_id,
            "node_id": self.node_id,
            "possession_state": self.possession_state,
            "verified_pieces": sorted(self.verified_pieces),
            "total_pieces": self.total_pieces,
            "epoch": self.epoch,
            "anchor_id": self.anchor_id,
            "last_challenge_ok": self.last_challenge_ok,
            "kind": "verified",
        }


class PossessionTracker:
    def __init__(self):
        self.claims: Dict[str, Dict[str, PossessionClaim]] = {}  # asset → node → claim
        self.verified: Dict[str, Dict[str, VerifiedPossession]] = {}

    def record_claim(self, claim: PossessionClaim):
        self.claims.setdefault(claim.asset_id, {})[claim.node_id] = claim

    def mark_verified_piece(
        self,
        asset_id: str,
        node_id: str,
        piece_index: int,
        *,
        total_pieces: int = 0,
        manifest_hash: str = "",
        epoch: Optional[int] = None,
        anchor_id: Optional[str] = None,
    ):
        bucket = self.verified.setdefault(asset_id, {})
        vp = bucket.get(node_id) or VerifiedPossession(asset_id=asset_id, node_id=node_id)
        vp.verified_pieces.add(piece_index)
        vp.last_challenge_ok = time.time()
        if total_pieces:
            vp.total_pieces = total_pieces
        if manifest_hash:
            vp.manifest_hash = manifest_hash
        if epoch is not None:
            vp.epoch = epoch
        if anchor_id:
            vp.anchor_id = anchor_id
        vp.refresh_state()
        bucket[node_id] = vp

    def claimed_holders(self, asset_id: str) -> List[str]:
        return list(self.claims.get(asset_id, {}).keys())

    def verified_holders(self, asset_id: str, min_pieces: int = 1) -> List[str]:
        out = []
        for node_id, vp in self.verified.get(asset_id, {}).items():
            if len(vp.verified_pieces) >= min_pieces:
                out.append(node_id)
        return out

    def evidence(self, asset_id: str, node_id: str) -> Optional[Dict[str, Any]]:
        vp = self.verified.get(asset_id, {}).get(node_id)
        return vp.to_dict() if vp else None

    def challenge_local(
        self,
        *,
        piece_bytes: bytes,
        piece_index: int,
        piece_hashes: List[str],
        root_hex: str,
        from_node: str,
        asset_id: str,
    ) -> bool:
        """
        Local verification of a challenged piece.
        On success, upgrades that piece to verified for from_node.
        """
        ok = verify_piece(piece_bytes, piece_index, piece_hashes, root_hex)
        if ok:
            self.mark_verified_piece(
                asset_id,
                from_node,
                piece_index,
                total_pieces=len(piece_hashes),
            )
        return ok


def content_id_from_pieces(piece_hashes: List[str]) -> str:
    """Stable content id from ordered piece hashes (immutable asset identity input)."""
    return hashlib.sha256("".join(h.lower() for h in piece_hashes).encode()).hexdigest()
