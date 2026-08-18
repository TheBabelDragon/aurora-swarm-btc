"""
Canonical commitment payload for Bitcoin attestation.

Design goals:
- Fit comfortably in OP_RETURN (≤80 bytes payload is ideal; we keep a short form)
- Be unambiguous and versioned
- Allow batching later via Merkle roots without breaking v1 single-asset form

Short form (default):
  AURORA1|<16-hex commitment prefix>

Full form (for logs / external indexers, not necessarily on-chain):
  {
    "v": 1,
    "c": "<64-hex commitment>",
    "a": "<asset_id prefix>",
    "t": <unix ts>
  }
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

MAGIC = "AURORA1"
OP_RETURN_MAX = 80


def short_op_return_payload(commitment: str) -> bytes:
    """
    Compact on-chain payload.

    Format: AURORA1|<first 16 hex chars of commitment>
    Length: 7 + 1 + 16 = 24 bytes — well under OP_RETURN limits.
    """
    prefix = commitment.lower().replace("0x", "")[:16]
    s = f"{MAGIC}|{prefix}"
    raw = s.encode("ascii")
    if len(raw) > OP_RETURN_MAX:
        raise ValueError("OP_RETURN payload too large")
    return raw


def full_record_payload(
    commitment: str,
    asset_id: str,
    *,
    ts: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Richer off-chain / indexer-friendly record."""
    body = {
        "v": 1,
        "c": commitment.lower().replace("0x", ""),
        "a": asset_id[:40],
        "t": int(ts or time.time()),
    }
    if extra:
        body["x"] = extra
    return body


def full_record_json(commitment: str, asset_id: str, **kwargs) -> str:
    return json.dumps(full_record_payload(commitment, asset_id, **kwargs), separators=(",", ":"), sort_keys=True)


def parse_short_payload(data: bytes) -> Optional[str]:
    """Return commitment prefix if this looks like an Aurora short payload."""
    try:
        s = data.decode("ascii")
    except Exception:
        return None
    if not s.startswith(MAGIC + "|"):
        return None
    prefix = s.split("|", 1)[1].strip().lower()
    if len(prefix) < 8 or any(c not in "0123456789abcdef" for c in prefix):
        return None
    return prefix
