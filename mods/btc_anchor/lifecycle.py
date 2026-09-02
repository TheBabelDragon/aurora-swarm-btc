"""
Anchor lifecycle.

A locally observed transaction is never a confirmed anchor.
Confirmation depth is required before an anchor becomes authoritative.

    UNANCHORED
        ↓
    COMMITMENT_PENDING
        ↓
    BROADCAST
        ↓
    INCLUDED
        ↓
    CONFIRMED

Also permitted:

    INCLUDED
        ↓
    REORGED
        ↓
    RE_ANCHOR_REQUIRED

Confirmed → REORGED is also valid when the inclusion block leaves the
canonical chain.
"""

from __future__ import annotations

import os
from typing import FrozenSet, Optional

UNANCHORED = "UNANCHORED"
COMMITMENT_PENDING = "COMMITMENT_PENDING"
BROADCAST = "BROADCAST"
INCLUDED = "INCLUDED"
CONFIRMED = "CONFIRMED"
REORGED = "REORGED"
RE_ANCHOR_REQUIRED = "RE_ANCHOR_REQUIRED"

ALL_STATUSES: FrozenSet[str] = frozenset(
    {
        UNANCHORED,
        COMMITMENT_PENDING,
        BROADCAST,
        INCLUDED,
        CONFIRMED,
        REORGED,
        RE_ANCHOR_REQUIRED,
    }
)

TRANSITIONS = {
    UNANCHORED: frozenset({COMMITMENT_PENDING, BROADCAST}),
    COMMITMENT_PENDING: frozenset({BROADCAST, INCLUDED, COMMITMENT_PENDING}),
    BROADCAST: frozenset({INCLUDED, BROADCAST, REORGED}),
    INCLUDED: frozenset({CONFIRMED, REORGED, INCLUDED}),
    CONFIRMED: frozenset({REORGED, CONFIRMED}),
    REORGED: frozenset({RE_ANCHOR_REQUIRED, REORGED}),
    RE_ANCHOR_REQUIRED: frozenset({COMMITMENT_PENDING, BROADCAST, INCLUDED, RE_ANCHOR_REQUIRED}),
}

# Legacy mesh statuses from earlier btc_anchor versions.
_LEGACY = {
    "recorded": COMMITMENT_PENDING,
    "pending_broadcast": COMMITMENT_PENDING,
    "submitted": BROADCAST,
    "confirmed": CONFIRMED,
    "failed": RE_ANCHOR_REQUIRED,
    "mesh_record": COMMITMENT_PENDING,
}


def normalize_status(status: Optional[str]) -> str:
    if not status:
        return UNANCHORED
    raw = str(status).strip()
    if raw in ALL_STATUSES:
        return raw
    mapped = _LEGACY.get(raw.lower())
    if mapped:
        return mapped
    upper = raw.upper().replace("-", "_").replace(" ", "_")
    if upper in ALL_STATUSES:
        return upper
    return UNANCHORED


def can_transition(src: str, dst: str) -> bool:
    src_n = normalize_status(src)
    dst_n = normalize_status(dst)
    if src_n == dst_n:
        return True
    return dst_n in TRANSITIONS.get(src_n, frozenset())


def transition(src: str, dst: str) -> str:
    src_n = normalize_status(src)
    dst_n = normalize_status(dst)
    if not can_transition(src_n, dst_n):
        raise ValueError(f"illegal anchor transition {src_n} → {dst_n}")
    return dst_n


def default_confirmation_depth() -> int:
    raw = os.getenv("AURORA_BTC_CONFIRMATION_DEPTH", "6")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 6


def is_authoritative(status: str, *, canonical: bool, confirmations: int, depth: int) -> bool:
    """A locally observed tx is never authoritative on its own."""
    st = normalize_status(status)
    if st != CONFIRMED:
        return False
    if not canonical:
        return False
    return int(confirmations) >= int(depth)
