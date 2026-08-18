"""
Commitment scheme for Asset Fabric manifests.

We deliberately keep this simple and deterministic so the same asset
always produces the same commitment across nodes and over time.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional


def canonical_manifest_payload(manifest_like: Dict[str, Any]) -> bytes:
    """
    Produce a stable byte encoding of the fields that define identity.

    Only content-critical fields are included so cosmetic changes
    (display name tweaks, extra provenance notes) do not change the
    commitment unless the caller puts them in provenance deliberately.
    """
    payload = {
        "asset_id": manifest_like.get("asset_id") or manifest_like.get("infohash"),
        "content_hash": manifest_like.get("content_hash") or manifest_like.get("asset_id"),
        "size": manifest_like.get("size"),
        "piece_size": manifest_like.get("piece_size"),
        "piece_hashes": manifest_like.get("piece_hashes") or [],
        "asset_type": manifest_like.get("asset_type", "blob"),
        "schema_version": manifest_like.get("schema_version", "1"),
    }
    # Sort keys for determinism
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_commitment(manifest_like: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> str:
    """
    SHA-256 commitment over the canonical manifest (+ optional extra salt/context).

    Returns a 64-char hex digest. This is what would later be placed in
    an OP_RETURN, inscription, or batch Merkle leaf.
    """
    body = canonical_manifest_payload(manifest_like)
    if extra:
        body += b"|" + json.dumps(extra, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def short_id(commitment: str) -> str:
    return commitment[:16]
