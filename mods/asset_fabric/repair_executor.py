"""
Execute repair / placement plans on the mesh.

Planner decides *where*. Executor asks the swarm to *get* the asset there.

Does not bypass verification — targets still verify-on-receive.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from comms.layer import CommsLayer, SwarmMessage

from .repair import PlacementPlan, RepairPlanner

logger = logging.getLogger("aurora.assets.repair_exec")


class RepairExecutor:
    def __init__(
        self,
        comms: CommsLayer,
        planner: RepairPlanner,
        *,
        list_candidates: Optional[Callable[[], List[str]]] = None,
    ):
        self.comms = comms
        self.planner = planner
        self.node_id = comms.node_id
        self.list_candidates = list_candidates or (lambda: [])
        self._history: List[Dict[str, Any]] = []

    def run_for_asset(self, asset_id: str, *,
                      min_pieces: int = 1,
                      candidates: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Measure availability → plan → publish ensure/repair directives.
        """
        nodes = candidates if candidates is not None else list(self.list_candidates())
        report = self.planner.availability(asset_id, min_pieces=min_pieces)
        plan = self.planner.plan_repair(asset_id, nodes, min_pieces=min_pieces)

        jobs = []
        for target in plan.targets:
            job = self._request_ensure(asset_id, target)
            jobs.append(job)

        entry = {
            "ts": time.time(),
            "asset_id": asset_id,
            "report": report.to_dict(),
            "plan": plan.to_dict(),
            "jobs": jobs,
        }
        self._history = (self._history + [entry])[-100:]
        try:
            self.comms.set_state(
                f"repair:last:{asset_id}",
                entry,
                expire=86400,
            )
        except Exception:
            pass

        logger.info(
            f"Repair exec asset={asset_id[:12]}… ok={report.ok} "
            f"targets={plan.targets} deficits={report.deficits}"
        )
        return entry

    def place_rs(self, asset_id: str, candidates: Optional[List[str]] = None) -> Dict[str, Any]:
        nodes = candidates if candidates is not None else list(self.list_candidates())
        plan = self.planner.plan_rs_placement(asset_id, nodes)
        jobs = []
        for i, target in enumerate(plan.targets):
            jobs.append(self._request_shard_hold(asset_id, target, shard_index=i))
        entry = {"ts": time.time(), "asset_id": asset_id, "plan": plan.to_dict(), "jobs": jobs}
        self._history.append(entry)
        return entry

    def _request_ensure(self, asset_id: str, target: str) -> Dict[str, Any]:
        payload = {
            "infohash": asset_id,
            "asset_id": asset_id,
            "target": target,
            "action": "ensure",
            "reason": "repair",
            "source": self.node_id,
        }
        try:
            msg = SwarmMessage(
                type="asset.needed",
                payload=payload,
                source=self.node_id,
                target=target,
            )
            self.comms.publish_message("asset.needed", msg)
            # Also broadcast so any capable node can help seed toward target
            msg2 = SwarmMessage(
                type="asset.repair",
                payload=payload,
                source=self.node_id,
            )
            self.comms.publish_message("asset.repair", msg2)
            return {"ok": True, "target": target, "action": "ensure"}
        except Exception as e:
            return {"ok": False, "target": target, "error": str(e)}

    def _request_shard_hold(self, asset_id: str, target: str, shard_index: int) -> Dict[str, Any]:
        payload = {
            "asset_id": asset_id,
            "target": target,
            "shard_index": shard_index,
            "action": "hold_shard",
            "source": self.node_id,
        }
        try:
            msg = SwarmMessage(
                type="asset.shard_place",
                payload=payload,
                source=self.node_id,
                target=target,
            )
            self.comms.publish_message("asset.shard_place", msg)
            return {"ok": True, **payload}
        except Exception as e:
            return {"ok": False, "target": target, "error": str(e)}

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._history[-limit:]
