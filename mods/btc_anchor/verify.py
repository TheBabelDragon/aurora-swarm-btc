"""Verification helpers for Aurora Bitcoin attestations.

A peer saying "asset X existed at block 900000" is evidence to verify, not truth.
Accept only a locally verified BTC anchor or an independently verifiable record.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from .commitment import (
    compute_artifact_commitment,
    compute_commitment,
    compute_manifest_hash,
)
from .lifecycle import CONFIRMED, REORGED, normalize_status
from .merkle import verify_proof
from .payload import parse_short_payload


class ClockVerificationError(ValueError):
    """Raised when a claimed clock/anchor fails verification."""


def verify_commitment(manifest_or_dict: Union[Dict[str, Any], Any], commitment: str) -> bool:
    """Recompute commitment from manifest fields and compare."""
    if hasattr(manifest_or_dict, "to_dict"):
        data = manifest_or_dict.to_dict()
    else:
        data = dict(manifest_or_dict)
    expected = compute_commitment(data)
    return expected.lower() == commitment.lower().replace("0x", "")


def verify_artifact_commitment(
    *,
    asset_id: str,
    manifest_hash: str,
    artifact_epoch: int,
    commitment: str,
    commitment_version: int = 1,
) -> bool:
    expected = compute_artifact_commitment(
        asset_id, manifest_hash, artifact_epoch, commitment_version=commitment_version
    )
    return expected.lower() == str(commitment).lower().replace("0x", "")


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


def verify_anchor_record(
    rec: Any,
    *,
    expected_asset_id: Optional[str] = None,
    expected_manifest_hash: Optional[str] = None,
    chain: Any = None,
) -> Dict[str, Any]:
    """
    Independently verify an anchor record.

    Rejects:
      - mismatched asset_id / manifest_hash / commitment
      - unverified / missing chain location
      - stale/reorged anchors presented as canonical
    """
    d = rec.to_dict() if hasattr(rec, "to_dict") else dict(rec)
    reasons = []
    asset_id = str(d.get("asset_id") or "")
    manifest_hash = str(d.get("manifest_hash") or "")
    epoch = d.get("artifact_epoch")
    commitment = str(d.get("commitment") or "")
    status = normalize_status(d.get("status"))

    if expected_asset_id and expected_asset_id != asset_id:
        reasons.append("mismatched_asset_id")
    if expected_manifest_hash and manifest_hash and expected_manifest_hash != manifest_hash:
        reasons.append("mismatched_manifest_hash")

    if epoch is None:
        reasons.append("missing_epoch")
    elif not verify_artifact_commitment(
        asset_id=asset_id,
        manifest_hash=manifest_hash,
        artifact_epoch=int(epoch),
        commitment=commitment,
        commitment_version=int(d.get("commitment_version") or 1),
    ):
        reasons.append("mismatched_commitment")

    canonical = bool(d.get("canonical"))
    if status == REORGED:
        reasons.append("reorged_anchor")
        canonical = False

    if chain is not None:
        txid = d.get("txid")
        block_hash = d.get("btc_block_hash")
        if not txid:
            reasons.append("unverified_anchor")
        else:
            loc = chain.tx_location(txid) if hasattr(chain, "tx_location") else None
            if loc is None:
                reasons.append("unverified_anchor")
            else:
                if block_hash and loc.block_hash != block_hash:
                    reasons.append("stale_or_reorged_anchor")
                if hasattr(chain, "is_canonical") and not chain.is_canonical(loc.block_hash):
                    reasons.append("stale_or_reorged_anchor")
                    canonical = False
    elif status not in (CONFIRMED,) or not canonical:
        # Without a chain view we can only check internal consistency.
        # A record that merely claims CONFIRMED is not locally verified.
        if status == CONFIRMED and not d.get("txid"):
            reasons.append("unverified_anchor")

    ok = not reasons
    return {
        "ok": ok,
        "accepted": ok and canonical and status == CONFIRMED,
        "reasons": reasons,
        "status": status,
        "canonical": canonical,
        "asset_id": asset_id,
        "manifest_hash": manifest_hash,
        "commitment": commitment,
    }


def reject_peer_clock_claim(
    claim: Dict[str, Any],
    *,
    local_record: Any = None,
    local_manifest_hash: Optional[str] = None,
    chain: Any = None,
) -> Dict[str, Any]:
    """
    Peer-supplied btc_height / block_hash is evidence, not truth.

    A claim is accepted only when it matches a locally verified or
    independently verifiable anchor record on the canonical chain.
    """
    reasons = []
    claimed_height = claim.get("btc_height") if isinstance(claim, dict) else getattr(claim, "btc_height", None)
    claimed_hash = claim.get("btc_block_hash") if isinstance(claim, dict) else getattr(claim, "btc_block_hash", None)
    claimed_manifest = (
        claim.get("manifest_hash") if isinstance(claim, dict) else getattr(claim, "manifest_hash", None)
    )
    claimed_asset = claim.get("asset_id") if isinstance(claim, dict) else getattr(claim, "asset_id", None)

    if local_manifest_hash and claimed_manifest and claimed_manifest != local_manifest_hash:
        reasons.append("mismatched_manifest_hash")

    if local_record is None:
        reasons.append("unverified_anchor")
        return {"ok": False, "accepted": False, "reasons": reasons}

    checked = verify_anchor_record(
        local_record,
        expected_asset_id=claimed_asset,
        expected_manifest_hash=local_manifest_hash or claimed_manifest,
        chain=chain,
    )
    reasons.extend(checked.get("reasons") or [])

    rec = local_record.to_dict() if hasattr(local_record, "to_dict") else dict(local_record)
    if claimed_height is not None and rec.get("btc_height") is not None:
        if int(claimed_height) != int(rec["btc_height"]):
            reasons.append("peer_supplied_arbitrary_btc_height")
    elif claimed_height is not None and rec.get("btc_height") is None:
        reasons.append("peer_supplied_arbitrary_btc_height")

    if claimed_hash and rec.get("btc_block_hash"):
        if str(claimed_hash) != str(rec["btc_block_hash"]):
            reasons.append("peer_supplied_arbitrary_block_hash")
    elif claimed_hash and not rec.get("btc_block_hash"):
        reasons.append("peer_supplied_arbitrary_block_hash")

    ok = not reasons and checked.get("ok")
    return {
        "ok": bool(ok),
        "accepted": bool(ok) and bool(checked.get("accepted")),
        "reasons": reasons,
    }


def verify_manifest_hash(manifest_or_dict: Union[Dict[str, Any], Any], manifest_hash: str) -> bool:
    if hasattr(manifest_or_dict, "to_dict"):
        data = manifest_or_dict.to_dict()
    else:
        data = dict(manifest_or_dict)
    return compute_manifest_hash(data) == str(manifest_hash).lower()
