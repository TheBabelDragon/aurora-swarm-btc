"""
Verified-availability repair planner.

Rules:
  - Claimed possession is not availability
  - Only verified pieces/shards count
  - Desired redundancy includes failure-domain diversity
  - Repair = detect → verify → quarantine → reconstruct → redistribute → verify
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

from .erasure import decode, encode
from .possession_verify import PossessionTracker
from .topology import TopologyRegistry

logger = logging.getLogger("aurora.assets.repair")


@dataclass
class RedundancyPolicy:
    """Minimum verified copies / shards and diversity floors."""

    min_verified_holders: int = 3
    min_sites: int = 1
    min_power: int = 2
    min_network: int = 2
    min_racks: int = 2
    # For RS-encoded assets
    n_data: int = 4
    n_parity: int = 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_verified_holders": self.min_verified_holders,
            "min_sites": self.min_sites,
            "min_power": self.min_power,
            "min_network": self.min_network,
            "min_racks": self.min_racks,
            "n_data": self.n_data,
            "n_parity": self.n_parity,
        }


@dataclass
class AvailabilityReport:
    asset_id: str
    claimed_holders: List[str] = field(default_factory=list)
    verified_holders: List[str] = field(default_factory=list)
    verified_count: int = 0
    sites: Set[str] = field(default_factory=set)
    power: Set[str] = field(default_factory=set)
    network: Set[str] = field(default_factory=set)
    racks: Set[str] = field(default_factory=set)
    policy: RedundancyPolicy = field(default_factory=RedundancyPolicy)
    ok: bool = False
    deficits: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "claimed_holders": self.claimed_holders,
            "verified_holders": self.verified_holders,
            "verified_count": self.verified_count,
            "sites": sorted(self.sites),
            "power": sorted(self.power),
            "network": sorted(self.network),
            "racks": sorted(self.racks),
            "policy": self.policy.to_dict(),
            "ok": self.ok,
            "deficits": self.deficits,
        }


@dataclass
class PlacementPlan:
    """Where to put shards/replicas next."""

    asset_id: str
    targets: List[str]  # node ids
    reason: str
    shard_indices: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "targets": self.targets,
            "reason": self.reason,
            "shard_indices": self.shard_indices,
        }


class RepairPlanner:
    def __init__(
        self,
        possession: PossessionTracker,
        topology: TopologyRegistry,
        policy: Optional[RedundancyPolicy] = None,
    ):
        self.possession = possession
        self.topology = topology
        self.policy = policy or RedundancyPolicy()

    def availability(self, asset_id: str, min_pieces: int = 1) -> AvailabilityReport:
        claimed = self.possession.claimed_holders(asset_id)
        verified = self.possession.verified_holders(asset_id, min_pieces=min_pieces)
        pol = self.policy
        report = AvailabilityReport(
            asset_id=asset_id,
            claimed_holders=claimed,
            verified_holders=verified,
            verified_count=len(verified),
            policy=pol,
        )
        report.sites = self.topology.domain_values("site", verified)
        report.power = self.topology.domain_values("power", verified)
        report.network = self.topology.domain_values("network", verified)
        report.racks = self.topology.domain_values("rack", verified)

        deficits = []
        if report.verified_count < pol.min_verified_holders:
            deficits.append(
                f"verified_holders {report.verified_count}<{pol.min_verified_holders}"
            )
        if len(report.sites) < pol.min_sites:
            deficits.append(f"sites {len(report.sites)}<{pol.min_sites}")
        if len(report.power) < pol.min_power:
            deficits.append(f"power {len(report.power)}<{pol.min_power}")
        if len(report.network) < pol.min_network:
            deficits.append(f"network {len(report.network)}<{pol.min_network}")
        if len(report.racks) < pol.min_racks:
            deficits.append(f"racks {len(report.racks)}<{pol.min_racks}")

        report.deficits = deficits
        report.ok = not deficits
        return report

    def plan_repair(
        self,
        asset_id: str,
        candidate_nodes: Sequence[str],
        *,
        min_pieces: int = 1,
    ) -> PlacementPlan:
        """
        Choose target nodes that improve verified count and domain diversity.
        Does not move bytes — only plans.
        """
        report = self.availability(asset_id, min_pieces=min_pieces)
        if report.ok:
            return PlacementPlan(asset_id=asset_id, targets=[], reason="policy_satisfied")

        verified_set = set(report.verified_holders)
        scored: List[tuple] = []
        for nid in candidate_nodes:
            if nid in verified_set:
                continue
            topo = self.topology.get(nid)
            gain = 0
            if topo:
                if topo.site not in report.sites:
                    gain += 4
                if topo.power not in report.power:
                    gain += 3
                if topo.network not in report.network:
                    gain += 3
                if topo.rack not in report.racks:
                    gain += 2
            else:
                gain += 1  # unknown still increases headcount
            scored.append((-gain, nid))

        scored.sort()
        need = max(0, self.policy.min_verified_holders - report.verified_count)
        # Also try to fix diversity even if count is met
        if need == 0 and report.deficits:
            need = min(2, len(scored))
        targets = [nid for _, nid in scored[: max(need, 0)]]
        return PlacementPlan(
            asset_id=asset_id,
            targets=targets,
            reason="repair_deficit: " + ",".join(report.deficits),
        )

    def plan_rs_placement(
        self,
        asset_id: str,
        candidate_nodes: Sequence[str],
        *,
        n_data: Optional[int] = None,
        n_parity: Optional[int] = None,
    ) -> PlacementPlan:
        """
        Assign shard indices to distinct nodes preferring domain diversity.
        """
        nd = n_data if n_data is not None else self.policy.n_data
        np_ = n_parity if n_parity is not None else self.policy.n_parity
        total = nd + np_
        if total == 0:
            return PlacementPlan(asset_id=asset_id, targets=[], reason="no_shards")

        # Greedy: pick nodes maximizing new domain coverage
        chosen: List[str] = []
        sites: Set[str] = set()
        power: Set[str] = set()
        network: Set[str] = set()
        racks: Set[str] = set()
        remaining = list(dict.fromkeys(candidate_nodes))

        for _ in range(min(total, len(remaining))):
            best = None
            best_gain = -1
            for nid in remaining:
                if nid in chosen:
                    continue
                topo = self.topology.get(nid)
                gain = 1
                if topo:
                    gain += 4 * (topo.site not in sites)
                    gain += 3 * (topo.power not in power)
                    gain += 3 * (topo.network not in network)
                    gain += 2 * (topo.rack not in racks)
                if gain > best_gain:
                    best_gain = gain
                    best = nid
            if best is None:
                break
            chosen.append(best)
            remaining = [n for n in remaining if n != best]
            topo = self.topology.get(best)
            if topo:
                sites.add(topo.site)
                power.add(topo.power)
                network.add(topo.network)
                racks.add(topo.rack)

        return PlacementPlan(
            asset_id=asset_id,
            targets=chosen,
            shard_indices=list(range(len(chosen))),
            reason=f"rs_placement n_data={nd} n_parity={np_}",
        )


def encode_important(data: bytes, policy: Optional[RedundancyPolicy] = None) -> Dict[str, Any]:
    """RS-encode an important asset for domain-aware distribution."""
    pol = policy or RedundancyPolicy()
    return encode(data, n_data=pol.n_data, n_parity=pol.n_parity)


def reconstruct_from_shards(
    shards: Sequence[Optional[bytes]],
    *,
    n_data: int,
    n_parity: int,
    shard_size: int,
    original_size: int,
) -> Optional[bytes]:
    return decode(
        shards,
        n_data=n_data,
        n_parity=n_parity,
        shard_size=shard_size,
        original_size=original_size,
    )
