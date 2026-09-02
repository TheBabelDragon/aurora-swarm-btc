"""
Canonical artifact clock.

Bitcoin supplies the scarce, externally verifiable temporal coordinate.
Local wall time is observation metadata only — never the artifact epoch.

    local_time      = observation metadata
    btc_height      = ordered epoch
    cumulative_work = scarcity/security weight
    block_hash      = cryptographic anchor

An artifact can exist before it is anchored.
An unanchored artifact has no authoritative Bitcoin epoch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

CLOCK_VERSION = 1

# Confidence is derived from the Bitcoin anchor lifecycle, never from a peer claim.
CONFIDENCE_NONE = "none"
CONFIDENCE_PENDING = "pending"
CONFIDENCE_INCLUDED = "included"
CONFIDENCE_CONFIRMED = "confirmed"
CONFIDENCE_REORGED = "reorged"

_CONFIDENCE = frozenset(
    {
        CONFIDENCE_NONE,
        CONFIDENCE_PENDING,
        CONFIDENCE_INCLUDED,
        CONFIDENCE_CONFIRMED,
        CONFIDENCE_REORGED,
    }
)


def confidence_from_status(status: Optional[str], *, confirmations: int = 0, depth: int = 6) -> str:
    """Map an anchor lifecycle status onto clock confidence."""
    if not status:
        return CONFIDENCE_NONE
    s = str(status).upper().replace("-", "_")
    if s in ("UNANCHORED",):
        return CONFIDENCE_NONE
    if s in ("REORGED", "RE_ANCHOR_REQUIRED", "REANCHOR_REQUIRED"):
        return CONFIDENCE_REORGED
    if s in ("CONFIRMED",):
        return CONFIDENCE_CONFIRMED
    if s in ("INCLUDED",):
        if confirmations >= depth:
            return CONFIDENCE_CONFIRMED
        return CONFIDENCE_INCLUDED
    if s in (
        "COMMITMENT_PENDING",
        "BROADCAST",
        "RECORDED",
        "PENDING_BROADCAST",
        "SUBMITTED",
    ):
        return CONFIDENCE_PENDING
    return CONFIDENCE_NONE


@dataclass(frozen=True)
class ArtifactClock:
    """One canonical temporal record for an artifact identity.

    `asset_id` is the content-addressed artifact identity.
    `anchor_id` is a temporal observation of that identity.
    They are never equal by construction when an anchor exists.
    """

    asset_id: str
    manifest_hash: str
    epoch: Optional[int]
    btc_height: Optional[int]
    btc_block_hash: Optional[str]
    btc_work: Optional[str]
    anchor_id: Optional[str]
    observed_at: float
    confidence: str

    def __post_init__(self):
        if self.confidence not in _CONFIDENCE:
            object.__setattr__(self, "confidence", CONFIDENCE_NONE)
        if self.confidence == CONFIDENCE_NONE:
            object.__setattr__(self, "epoch", None)
            object.__setattr__(self, "btc_height", None)
            object.__setattr__(self, "btc_block_hash", None)
            object.__setattr__(self, "btc_work", None)
            object.__setattr__(self, "anchor_id", None)

    @property
    def clock_version(self) -> int:
        return CLOCK_VERSION

    @property
    def is_authoritative(self) -> bool:
        """Only a locally verified, sufficiently confirmed canonical anchor is authoritative."""
        return self.confidence == CONFIDENCE_CONFIRMED and self.epoch is not None

    @property
    def is_anchored(self) -> bool:
        return self.anchor_id is not None and self.confidence not in (
            CONFIDENCE_NONE,
            CONFIDENCE_REORGED,
        )

    def canonical_tuple(
        self,
    ) -> Tuple[
        str,
        str,
        Optional[int],
        Optional[int],
        Optional[str],
        Optional[str],
        Optional[str],
        str,
    ]:
        """Fields two peers must derive identically from the same anchor.

        `observed_at` is informational and is excluded.
        """
        return (
            self.asset_id,
            self.manifest_hash,
            self.epoch,
            self.btc_height,
            self.btc_block_hash,
            self.btc_work,
            self.anchor_id,
            self.confidence,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clock_version": CLOCK_VERSION,
            "asset_id": self.asset_id,
            "manifest_hash": self.manifest_hash,
            "epoch": self.epoch,
            "btc_height": self.btc_height,
            "btc_block_hash": self.btc_block_hash,
            "btc_work": self.btc_work,
            "anchor_id": self.anchor_id,
            "observed_at": self.observed_at,
            "confidence": self.confidence,
            "authoritative": self.is_authoritative,
        }

    @classmethod
    def unanchored(
        cls,
        asset_id: str,
        manifest_hash: str,
        *,
        observed_at: float = 0.0,
    ) -> "ArtifactClock":
        return cls(
            asset_id=str(asset_id),
            manifest_hash=str(manifest_hash),
            epoch=None,
            btc_height=None,
            btc_block_hash=None,
            btc_work=None,
            anchor_id=None,
            observed_at=float(observed_at or 0.0),
            confidence=CONFIDENCE_NONE,
        )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ArtifactClock":
        return cls(
            asset_id=str(d["asset_id"]),
            manifest_hash=str(d.get("manifest_hash") or ""),
            epoch=_opt_int(d.get("epoch")),
            btc_height=_opt_int(d.get("btc_height")),
            btc_block_hash=_opt_str(d.get("btc_block_hash")),
            btc_work=_opt_str(d.get("btc_work")),
            anchor_id=_opt_str(d.get("anchor_id")),
            observed_at=float(d.get("observed_at") or 0.0),
            confidence=str(d.get("confidence") or CONFIDENCE_NONE),
        )

    @classmethod
    def from_anchor_record(
        cls,
        rec: Any,
        *,
        manifest_hash: str,
        confirmation_depth: int = 6,
    ) -> "ArtifactClock":
        """Deterministic derivation. Two peers with the same record get the same clock."""
        if rec is None:
            raise ValueError("anchor record required")
        if hasattr(rec, "to_dict"):
            d = rec.to_dict()
        else:
            d = dict(rec)
        asset_id = str(d.get("asset_id") or "")
        status = d.get("status")
        confirmations = int(d.get("confirmations") or 0)
        depth = int(d.get("confirmation_depth") or confirmation_depth)
        canonical = bool(d.get("canonical", False))
        confidence = confidence_from_status(status, confirmations=confirmations, depth=depth)
        if confidence == CONFIDENCE_CONFIRMED and not canonical:
            # A locally observed tx is never authoritative on a non-canonical block.
            confidence = CONFIDENCE_INCLUDED
        # observed_at is taken from the record so derivation is deterministic
        observed = d.get("included_at")
        if observed is None:
            observed = d.get("created_at") or 0.0
        epoch = _opt_int(d.get("artifact_epoch"))
        if epoch is None:
            epoch = _opt_int(d.get("btc_height"))
        return cls(
            asset_id=asset_id,
            manifest_hash=str(d.get("manifest_hash") or manifest_hash),
            epoch=epoch if confidence != CONFIDENCE_NONE else None,
            btc_height=_opt_int(d.get("btc_height")) if confidence != CONFIDENCE_NONE else None,
            btc_block_hash=_opt_str(d.get("btc_block_hash")) if confidence != CONFIDENCE_NONE else None,
            btc_work=_opt_str(d.get("btc_work")) if confidence != CONFIDENCE_NONE else None,
            anchor_id=_opt_str(d.get("anchor_id")) if confidence != CONFIDENCE_NONE else None,
            observed_at=float(observed or 0.0),
            confidence=confidence,
        )


def _opt_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
