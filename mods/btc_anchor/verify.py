"""Verification helpers for Aurora Bitcoin attestations."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from .commitment import compute_commitment
from .payload import parse_short_payload
from .merkle import verify_proof


def verify_commitment(manifest_or_dict: Union[Dict[str, Any], Any], commitment: str) -> bool:
    """Recompute commitment from manifest fields and compare."""
    if hasattr(manifest_or_dict, "to_dict"):
        data = manifest_or_dict.to_dict()
    else:
        data = dict(manifest_or_dict)
    expected = compute_commitment(data)
    return expected.lower() == commitment.lower().replace("0x", "")


def verify_op_return_prefix(op_return: bytes, commitment: str) -> bool:
    """Check that a short OP_RETURN payload matches the commitment prefix."""
    prefix = parse_short_payload(op_return)
    if not prefix:
        return False
    return commitment.lower().replace("0x", "").startswith(prefix)


def verify_merkle_inclusion(
    commitment: str,
    proof: list,
    root_hex: str,
) -> bool:
    try:
        return verify_proof(commitment, [(p[0], p[1]) for p in proof], root_hex)
    except Exception:
        return False
