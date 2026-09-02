"""
Commitment scheme for Asset Fabric manifests.

We deliberately keep this simple and deterministic so the same asset
always produces the same commitment across nodes and over time.

The Bitcoin commitment proves:

    "this exact artifact identity was known by epoch X"

It does NOT prove:

    "Bitcoin stores this artifact."

Do not commit the entire artifact payload.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

ARTIFACT_COMMITMENT_VERSION = 1


def canonical_manifest_payload(manifest_like: Dict[str, Any]) -> bytes:
    """
    Produce a stable byte encoding of the fields that define identity.

    Only content-critical fields are included so cosmetic changes
    (display name tweaks, extra provenance notes, temporal metadata)
    do not change the commitment unless the caller puts them in
    provenance deliberately.
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
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_manifest_hash(manifest_like: Dict[str, Any]) -> str:
    """Content-addressed hash of identity fields. Temporal metadata is excluded."""
    return hashlib.sha256(canonical_manifest_payload(manifest_like)).hexdigest()


def compute_commitment(manifest_like: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> str:
    """
    SHA-256 commitment over the canonical manifest (+ optional extra salt/context).

    Returns a 64-char hex digest. This is what would later be placed in
    an OP_RETURN, inscription, or batch Merkle leaf.

    Prefer `compute_artifact_commitment` for the artifact-clock path: it binds
    identity to a Bitcoin epoch without embedding the payload.
    """
    body = canonical_manifest_payload(manifest_like)
    if extra:
        body += b"|" + json.dumps(extra, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def artifact_commitment_payload(
    asset_id: str,
    manifest_hash: str,
    artifact_epoch: int,
    commitment_version: int = ARTIFACT_COMMITMENT_VERSION,
) -> bytes:
    payload = {
        "asset_id": str(asset_id),
        "manifest_hash": str(manifest_hash),
        "artifact_epoch": int(artifact_epoch),
        "commitment_version": int(commitment_version),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_artifact_commitment(
    asset_id: str,
    manifest_hash: str,
    artifact_epoch: int,
    commitment_version: int = ARTIFACT_COMMITMENT_VERSION,
) -> str:
    """Bind artifact identity to a Bitcoin epoch. Never includes piece bytes."""
    return hashlib.sha256(
        artifact_commitment_payload(
            asset_id, manifest_hash, artifact_epoch, commitment_version=commitment_version
        )
    ).hexdigest()


def derive_anchor_id(
    asset_id: str,
    manifest_hash: str,
    btc_block_hash: str,
    commitment: str,
) -> str:
    """
    Temporal observation identity. Distinct from asset_id:

        asset_id  !=  anchor_id
        same asset + different anchor  =  same artifact, different observation
    """
    body = {
        "asset_id": str(asset_id),
        "manifest_hash": str(manifest_hash),
        "btc_block_hash": str(btc_block_hash),
        "commitment": str(commitment),
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def short_id(commitment: str) -> str:
    return commitment[:16]
