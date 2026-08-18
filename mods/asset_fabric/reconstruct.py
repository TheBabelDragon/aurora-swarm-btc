"""
Reconstruct an important asset from Reed-Solomon shards on disk/mesh.

Solves: assets must not live on a single box forever.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .erasure import decode

logger = logging.getLogger("aurora.assets.reconstruct")


def load_local_shards(
    storage_dir: Path,
    asset_id: str,
    shard_count: int,
) -> List[Optional[bytes]]:
    shards: List[Optional[bytes]] = []
    for i in range(shard_count):
        p = Path(storage_dir) / f"{asset_id}.shard.{i:04d}"
        if p.exists():
            shards.append(p.read_bytes())
        else:
            shards.append(None)
    return shards


def reconstruct_important(
    *,
    shards: Sequence[Optional[bytes]],
    n_data: int,
    n_parity: int,
    shard_size: int,
    original_size: int,
    content_hash: Optional[str] = None,
) -> Dict[str, Any]:
    present = sum(1 for s in shards if s is not None)
    if present < n_data:
        return {
            "ok": False,
            "error": f"need {n_data} shards, have {present}",
            "present": present,
        }
    out = decode(
        list(shards),
        n_data=n_data,
        n_parity=n_parity,
        shard_size=shard_size,
        original_size=original_size,
    )
    if out is None:
        return {"ok": False, "error": "decode failed", "present": present}
    if content_hash:
        import hashlib

        if hashlib.sha256(out).hexdigest() != content_hash:
            return {"ok": False, "error": "content_hash mismatch after decode"}
    return {
        "ok": True,
        "size": len(out),
        "data": out,
        "present_shards": present,
    }


def reconstruct_from_dir(
    storage_dir: Path,
    asset_id: str,
    encoding: Dict[str, Any],
) -> Dict[str, Any]:
    n_data = int(encoding["n_data"])
    n_parity = int(encoding["n_parity"])
    shard_size = int(encoding["shard_size"])
    original_size = int(encoding["original_size"])
    shard_count = int(encoding.get("shard_count") or (n_data + n_parity))
    shards = load_local_shards(Path(storage_dir), asset_id, shard_count)
    result = reconstruct_important(
        shards=shards,
        n_data=n_data,
        n_parity=n_parity,
        shard_size=shard_size,
        original_size=original_size,
        content_hash=encoding.get("content_hash"),
    )
    # Don't echo full data in logs; caller decides
    if result.get("ok"):
        data = result.pop("data")
        result["data"] = data
    return result
