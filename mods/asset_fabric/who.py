"""
Answer: who holds this asset — claimed vs verified.

This is the product answer to "trust is SSH and spreadsheets."
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .possession_verify import PossessionTracker
from .repair import RepairPlanner, RedundancyPolicy
from .topology import TopologyRegistry


def who_holds(
    asset_id: str,
    *,
    possession: PossessionTracker,
    topology: Optional[TopologyRegistry] = None,
    policy: Optional[RedundancyPolicy] = None,
    claimed_from_mesh: Optional[List[str]] = None,
    min_pieces: int = 1,
) -> Dict[str, Any]:
    asset_id = str(asset_id).strip().lower()
    claimed = list(possession.claimed_holders(asset_id))
    if claimed_from_mesh:
        for n in claimed_from_mesh:
            if n not in claimed:
                claimed.append(n)
    verified = possession.verified_holders(asset_id, min_pieces=min_pieces)

    report = None
    if topology is not None:
        planner = RepairPlanner(possession, topology, policy or RedundancyPolicy())
        report = planner.availability(asset_id, min_pieces=min_pieces)

    return {
        "asset_id": asset_id,
        "claimed_holders": sorted(set(claimed)),
        "verified_holders": sorted(set(verified)),
        "claimed_count": len(set(claimed)),
        "verified_count": len(set(verified)),
        "rule": "claimed ≠ availability; verified = availability",
        "availability": report.to_dict() if report else None,
    }
