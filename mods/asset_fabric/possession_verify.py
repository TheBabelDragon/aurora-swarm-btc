"""
Claimed vs verified possession.

Claims are cheap. Verification is a challenge: produce bytes + proof.
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
    epoch: int = 0
    claimed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "node_id": self.node_id,
            "pieces": sorted(self.piece_bitmap),
            "epoch": self.epoch,
            "claimed_at": self.claimed_at,
            "kind": "claimed",
        }


@dataclass
class VerifiedPossession:
    asset_id: str
    node_id: str
    verified_pieces: Set[int] = field(default_factory=set)
    last_challenge_ok: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "node_id": self.node_id,
            "verified_pieces": sorted(self.verified_pieces),
            "last_challenge_ok": self.last_challenge_ok,
            "kind": "verified",
        }


class PossessionTracker:
    def __init__(self):
        self.claims: Dict[str, Dict[str, PossessionClaim]] = {}  # asset → node → claim
        self.verified: Dict[str, Dict[str, VerifiedPossession]] = {}

    def record_claim(self, claim: PossessionClaim):
        self.claims.setdefault(claim.asset_id, {})[claim.node_id] = claim

    def mark_verified_piece(self, asset_id: str, node_id: str, piece_index: int):
        bucket = self.verified.setdefault(asset_id, {})
        vp = bucket.get(node_id) or VerifiedPossession(asset_id=asset_id, node_id=node_id)
        vp.verified_pieces.add(piece_index)
        vp.last_challenge_ok = time.time()
        bucket[node_id] = vp

    def claimed_holders(self, asset_id: str) -> List[str]:
        return list(self.claims.get(asset_id, {}).keys())

    def verified_holders(self, asset_id: str, min_pieces: int = 1) -> List[str]:
        out = []
        for node_id, vp in self.verified.get(asset_id, {}).items():
            if len(vp.verified_pieces) >= min_pieces:
                out.append(node_id)
        return out

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
            self.mark_verified_piece(asset_id, from_node, piece_index)
        return ok


def content_id_from_pieces(piece_hashes: List[str]) -> str:
    """Stable content id from ordered piece hashes (immutable asset identity input)."""
    return hashlib.sha256("".join(h.lower() for h in piece_hashes).encode()).hexdigest()
