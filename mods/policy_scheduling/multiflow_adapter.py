"""MultiFlow scheduling adapter.

Feature-flagged (AURORA_MULTIFLOW_ENABLED, default off). Uses verified MultiFlow
interfaces when the package is importable (site-packages or vendor/); otherwise
reports unavailable and never pretends to dispatch work.

Baseline Aurora scheduler remains the execution path unless controlled
activation explicitly hands off through this adapter after AEGIS authorization.
"""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .schema import PolicyPreferences, SimulationResult

logger = logging.getLogger("aurora.policy.multiflow")


def _ensure_vendor_path() -> None:
    """Prefer vendored MultiFlow under repo vendor/ so import works offline."""
    root = Path(__file__).resolve().parents[2] / "vendor"
    if root.is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))


class MultiFlowAvailability(str, Enum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    PACKAGE_MISSING = "package_missing"
    ERROR = "error"


def _feature_enabled() -> bool:
    return os.getenv("AURORA_MULTIFLOW_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


class MultiFlowAdapter:
    """Translate Aurora state + policy preferences into MultiFlow inputs."""

    def __init__(self) -> None:
        self._mf = None
        self._import_error: Optional[str] = None
        self._try_import()

    def _try_import(self) -> None:
        _ensure_vendor_path()
        try:
            import multiflow  # type: ignore

            self._mf = multiflow
            self._import_error = None
        except Exception as e:
            self._mf = None
            self._import_error = str(e)
            logger.info("MultiFlow package not importable: %s", e)

    @property
    def availability(self) -> MultiFlowAvailability:
        if not _feature_enabled():
            return MultiFlowAvailability.DISABLED
        if self._mf is None:
            return MultiFlowAvailability.PACKAGE_MISSING
        return MultiFlowAvailability.AVAILABLE

    def status(self) -> Dict[str, Any]:
        return {
            "feature_enabled": _feature_enabled(),
            "availability": self.availability.value,
            "import_error": self._import_error,
            "package": "multiflow" if self._mf else None,
            "execution_enabled": False,  # shadow-first; never auto-dispatch
            "vendor_path_checked": True,
        }

    def collect_snapshot(
        self,
        *,
        workers: Optional[List[Dict[str, Any]]] = None,
        quarantined: Optional[Set[str]] = None,
        revoked: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        workers = workers or []
        quarantined = quarantined or set()
        revoked = revoked or set()
        resources = []
        for w in workers:
            wid = w.get("node_id") or w.get("id") or "unknown"
            if wid in quarantined or wid in revoked:
                continue
            caps = list(w.get("capabilities") or [])
            meta = w.get("metadata") or {}
            healthy = meta.get("status") in (None, "mining", "idle", "online", "healthy")
            capacity = 1 if healthy or meta.get("status") in (None,) else 0
            resources.append(
                {
                    "id": wid,
                    "type": "worker",
                    "capabilities": caps,
                    "capacity": capacity,
                    "attributes": {"node_type": w.get("node_type"), "meta_status": meta.get("status")},
                }
            )
        return {
            "snapshot_version": f"snap-{uuid.uuid4().hex[:10]}",
            "ts": time.time(),
            "resources": resources,
            "worker_count": len(resources),
            "quarantined": sorted(quarantined),
            "revoked": sorted(revoked),
        }

    def simulate(
        self,
        preferences: PolicyPreferences,
        snapshot: Dict[str, Any],
        *,
        policy_version_id: str,
        current_plan: Optional[List[Dict[str, Any]]] = None,
    ) -> SimulationResult:
        t0 = time.time()
        current_plan = current_plan or []
        avail = self.availability

        if avail != MultiFlowAvailability.AVAILABLE:
            reason = {
                MultiFlowAvailability.DISABLED: "AURORA_MULTIFLOW_ENABLED is off; baseline scheduler remains active",
                MultiFlowAvailability.PACKAGE_MISSING: f"multiflow package unavailable: {self._import_error}",
                MultiFlowAvailability.ERROR: "multiflow adapter error",
            }.get(avail, "unavailable")
            proposed = self._local_rank(snapshot, preferences)
            added, removed, changed = self._diff_plans(current_plan, proposed)
            return SimulationResult(
                policy_version_id=policy_version_id,
                snapshot_version=snapshot.get("snapshot_version", "unknown"),
                multiflow_available=False,
                solver_identity="aurora-local-ranker",
                admissible=len(proposed) > 0 or snapshot.get("worker_count", 0) == 0,
                status="admissible" if proposed or not snapshot.get("resources") else "no_complete_solution",
                current_plan=current_plan,
                proposed_plan=proposed,
                added=added,
                removed=removed,
                changed=changed,
                blocking_reasons=[] if proposed else [reason],
                warnings=[reason, "Estimates only — MultiFlow not operational"],
                objective_estimate=preferences.normalized_weights(),
                duration_ms=round((time.time() - t0) * 1000, 2),
            )

        try:
            return self._simulate_with_multiflow(
                preferences, snapshot, policy_version_id=policy_version_id, current_plan=current_plan, t0=t0
            )
        except Exception as e:
            logger.warning("MultiFlow simulate failed: %s", e)
            return SimulationResult(
                policy_version_id=policy_version_id,
                snapshot_version=snapshot.get("snapshot_version", "unknown"),
                multiflow_available=True,
                solver_identity="multiflow-error",
                admissible=False,
                status="error",
                current_plan=current_plan,
                blocking_reasons=[str(e)],
                warnings=["Solver failure; baseline scheduler unchanged"],
                duration_ms=round((time.time() - t0) * 1000, 2),
            )

    def _simulate_with_multiflow(
        self,
        preferences: PolicyPreferences,
        snapshot: Dict[str, Any],
        *,
        policy_version_id: str,
        current_plan: List[Dict[str, Any]],
        t0: float,
    ) -> SimulationResult:
        assert self._mf is not None
        from datetime import datetime, timedelta, timezone

        mf = self._mf
        now = datetime.now(timezone.utc)
        window = mf.TimeWindow(start=now, end=now + timedelta(hours=1))

        resources = []
        for r in snapshot.get("resources") or []:
            resources.append(
                mf.Resource(
                    id=r["id"],
                    type=mf.ResourceType.WORKER,
                    name=r["id"],
                    capabilities=r.get("capabilities") or [],
                    availability=[window] if r.get("capacity", 0) > 0 else [],
                    capacity=max(0, int(r.get("capacity", 1))),
                )
            )

        tasks = []
        for r in resources:
            if r.capacity <= 0:
                continue
            tasks.append(
                mf.Task(
                    id=f"task-{r.id}",
                    name=f"maintain:{r.id}",
                    requirements=[],
                    window=window,
                    attributes={"kind": "aurora_probe"},
                )
            )

        if not resources:
            return SimulationResult(
                policy_version_id=policy_version_id,
                snapshot_version=snapshot.get("snapshot_version", "unknown"),
                multiflow_available=True,
                solver_identity="ClassicalSolver",
                admissible=False,
                status="no_complete_solution",
                current_plan=current_plan,
                blocking_reasons=["No healthy workers available"],
                duration_ms=round((time.time() - t0) * 1000, 2),
            )

        problem = mf.SchedulingProblem(
            resources=resources,
            tasks=tasks
            or [mf.Task(id="noop", name="noop", requirements=[], window=window)],
            attributes={
                "policy_weights": preferences.normalized_weights(),
                "recovery_strategy": preferences.recovery_strategy.value,
            },
        )

        engine = mf.LiveEngine(initial_problem=problem)
        result = engine.recalculate()

        admissible_list = result.get("admissible") or result.get("admissible_candidates") or []
        status_raw = str(result.get("status") or result.get("solver_status") or "")
        violations = []
        if isinstance(result.get("validation"), dict):
            violations = list(result["validation"].get("violations") or [])

        proposed: List[Dict[str, Any]] = []
        if admissible_list:
            cand = admissible_list[0]
            assignments = getattr(cand, "assignments", None) or (
                cand.get("assignments") if isinstance(cand, dict) else []
            )
            for a in assignments or []:
                if hasattr(a, "model_dump"):
                    proposed.append(a.model_dump())
                elif isinstance(a, dict):
                    proposed.append(a)
                else:
                    proposed.append({"raw": str(a)})

        no_sol = not proposed and ("INFEASIBLE" in status_raw.upper() or not admissible_list)
        added, removed, changed = self._diff_plans(current_plan, proposed)

        return SimulationResult(
            policy_version_id=policy_version_id,
            snapshot_version=snapshot.get("snapshot_version", "unknown"),
            multiflow_available=True,
            solver_identity=getattr(engine.solver, "name", None) or type(engine.solver).__name__,
            admissible=bool(proposed) or (not tasks and not no_sol),
            status="no_complete_solution" if no_sol else "admissible",
            current_plan=current_plan,
            proposed_plan=proposed,
            added=added,
            removed=removed,
            changed=changed,
            constraint_violations=[str(v) for v in violations],
            blocking_reasons=["NO_COMPLETE_SOLUTION"] if no_sol else [],
            objective_estimate=preferences.normalized_weights(),
            warnings=["Simulation only — execution not dispatched"],
            duration_ms=round((time.time() - t0) * 1000, 2),
            evidence_ref=str(result.get("evidence_id") or ""),
        )

    def _local_rank(
        self, snapshot: Dict[str, Any], preferences: PolicyPreferences
    ) -> List[Dict[str, Any]]:
        weights = preferences.normalized_weights()
        plan = []
        for r in snapshot.get("resources") or []:
            if int(r.get("capacity", 0)) <= 0:
                continue
            score = (
                weights["load_balancing"] * 1.0
                + weights["latency"] * 0.8
                + weights["energy_efficiency"] * 0.5
            )
            plan.append(
                {
                    "resource_id": r["id"],
                    "task_id": f"probe-{r['id']}",
                    "score_estimate": round(score, 4),
                    "estimate": True,
                }
            )
        return plan

    @staticmethod
    def _diff_plans(
        current: List[Dict[str, Any]], proposed: List[Dict[str, Any]]
    ) -> tuple:
        def key(a: Dict[str, Any]) -> str:
            return f"{a.get('resource_id') or a.get('resource')}|{a.get('task_id') or a.get('task')}"

        cur_map = {key(a): a for a in current}
        prop_map = {key(a): a for a in proposed}
        added = [prop_map[k] for k in prop_map if k not in cur_map]
        removed = [cur_map[k] for k in cur_map if k not in prop_map]
        changed = [
            {"from": cur_map[k], "to": prop_map[k]}
            for k in prop_map
            if k in cur_map and cur_map[k] != prop_map[k]
        ]
        return added, removed, changed
