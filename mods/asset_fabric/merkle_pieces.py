"""
Merkle tree over piece hashes for Byzantine-safe piece verification.

Given ordered piece content hashes (sha256 hex), build a root and
inclusion proofs so receivers can verify a piece against the manifest
without trusting the sender.
"""

from __future__ import annotations

import hashlib
from typing import List, Sequence, Tuple


def _h(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def piece_leaf(piece_hash_hex: str) -> bytes:
    return _h(b"AURORA_PIECE|" + piece_hash_hex.lower().encode("ascii"))


def merkle_root_from_piece_hashes(piece_hashes: Sequence[str]) -> str:
    if not piece_hashes:
        return _h(b"AURORA_EMPTY_PIECES").hex()
    level = [piece_leaf(h) for h in piece_hashes]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            nxt.append(_h(left + right))
        level = nxt
    return level[0].hex()


def merkle_proof(piece_hashes: Sequence[str], index: int) -> List[Tuple[str, str]]:
    """List of (sibling_hex, side) with side in {'L','R'}."""
    if index < 0 or index >= len(piece_hashes):
        raise IndexError("piece index out of range")
    level = [piece_leaf(h) for h in piece_hashes]
    idx = index
    proof: List[Tuple[str, str]] = []
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            if i == idx or i + 1 == idx:
                if idx == i:
                    proof.append((right.hex(), "R"))
                else:
                    proof.append((left.hex(), "L"))
                idx = len(nxt)
            nxt.append(_h(left + right))
        level = nxt
    return proof


def verify_piece(
    piece_bytes: bytes,
    piece_index: int,
    piece_hashes: Sequence[str],
    root_hex: str,
    proof: List[Tuple[str, str]] | None = None,
) -> bool:
    """
    Verify piece content hash matches manifest slot and (optionally) Merkle proof.

    If proof is None, proof is derived from piece_hashes (honest helper path).
    Receivers that only have root + proof still verify without full hash list.
    """
    if piece_index < 0 or piece_index >= len(piece_hashes):
        return False
    digest = hashlib.sha256(piece_bytes).hexdigest()
    if digest != piece_hashes[piece_index].lower():
        return False
    if proof is None:
        try:
            proof = merkle_proof(piece_hashes, piece_index)
        except Exception:
            return False
    node = piece_leaf(digest)
    for sibling_hex, side in proof:
        sib = bytes.fromhex(sibling_hex)
        node = _h(node + sib) if side == "R" else _h(sib + node)
    return node.hex() == root_hex.lower()


def verify_proof_only(
    piece_hash_hex: str,
    proof: List[Tuple[str, str]],
    root_hex: str,
) -> bool:
    node = piece_leaf(piece_hash_hex)
    for sibling_hex, side in proof:
        sib = bytes.fromhex(sibling_hex)
        node = _h(node + sib) if side == "R" else _h(sib + node)
    return node.hex() == root_hex.lower()
