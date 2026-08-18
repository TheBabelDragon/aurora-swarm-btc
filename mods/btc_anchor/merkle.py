"""
Merkle batching for asset commitments.

One on-chain OP_RETURN can commit to many assets via a Merkle root,
keeping fees low while preserving per-asset proofs off-chain.
"""

from __future__ import annotations

import hashlib
from typing import List, Optional, Sequence, Tuple


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def leaf_hash(commitment_hex: str) -> bytes:
    c = commitment_hex.lower().replace("0x", "").encode("ascii")
    return _h(b"AURORA_LEAF|" + c)


def merkle_root(commitment_hexes: Sequence[str]) -> str:
    if not commitment_hexes:
        return _h(b"AURORA_EMPTY").hex()
    level = [leaf_hash(c) for c in commitment_hexes]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            nxt.append(_h(left + right))
        level = nxt
    return level[0].hex()


def merkle_proof(commitment_hexes: Sequence[str], index: int) -> List[Tuple[str, str]]:
    """
    Return list of (sibling_hex, side) where side is 'L' or 'R'
    meaning the sibling is on that side of the combined hash.
    """
    if index < 0 or index >= len(commitment_hexes):
        raise IndexError("leaf index out of range")
    level = [leaf_hash(c) for c in commitment_hexes]
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


def verify_proof(commitment_hex: str, proof: List[Tuple[str, str]], root_hex: str) -> bool:
    node = leaf_hash(commitment_hex)
    for sibling_hex, side in proof:
        sib = bytes.fromhex(sibling_hex)
        if side == "R":
            node = _h(node + sib)
        else:
            node = _h(sib + node)
    return node.hex() == root_hex.lower()


def batch_op_return_payload(root_hex: str, count: int) -> bytes:
    """
    Compact batch payload:
      AURORA1B|<16-hex root>|<count>
    """
    prefix = root_hex.lower()[:16]
    s = f"AURORA1B|{prefix}|{int(count)}"
    raw = s.encode("ascii")
    if len(raw) > 80:
        raise ValueError("batch OP_RETURN too large")
    return raw
