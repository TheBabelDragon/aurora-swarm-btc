"""
Important-asset publish: Reed-Solomon encode + domain placement directives.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .erasure import encode
from .repair import RedundancyPolicy, RepairPlanner
from .topology import TopologyRegistry

logger = logging.getLogger("aurora.assets.important")


def encode_and_plan(
    data: bytes,
    *,
    asset_id: str,
    planner: Optional[RepairPlanner] = None,
    candidates: Optional[List[str]] = None,
    policy: Optional[RedundancyPolicy] = None,
) -> Dict[str, Any]:
    pol = policy or RedundancyPolicy()
    enc = encode(data, n_data=pol.n_data, n_parity=pol.n_parity)
    plan = None
    if planner is not None and candidates:
        plan = planner.plan_rs_placement(
            asset_id,
            candidates,
            n_data=pol.n_data,
            n_parity=pol.n_parity,
        )
    return {
        "encoding": {
            "code": enc["code"],
            "n_data": enc["n_data"],
            "n_parity": enc["n_parity"],
            "shard_size": enc["shard_size"],
            "original_size": enc["original_size"],
            "content_hash": enc["content_hash"],
            "shard_count": len(enc["shards"]),
        },
        "shards": enc["shards"],
        "placement": plan.to_dict() if plan else None,
    }


def write_shards(storage_dir: Path, asset_id: str, shards: List[bytes]) -> List[str]:
    storage_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, sh in enumerate(shards):
        p = storage_dir / f"{asset_id}.shard.{i:04d}"
        p.write_bytes(sh)
        paths.append(str(p))
    return paths
