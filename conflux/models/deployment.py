"""Deployment planning and execution records.

v0.1 defaults to dry-run.
No automatic deploy to Aurora infrastructure.
No arbitrary remote shell.
Rollback references a previously verified release.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DeploymentStatus(str, Enum):
    PLANNED = "planned"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"
    DRY_RUN = "dry_run"


@dataclass
class DeploymentPlan:
    """Plan for deploying a release to a target."""

    plan_id: str
    project_id: str
    release_id: str
    target_id: str
    adapter: str = "dry_run"  # dry_run | local
    steps: List[Dict[str, Any]] = field(default_factory=list)
    health_checks: List[str] = field(default_factory=list)
    rollback_release_id: str = ""
    created_at: float = field(default_factory=time.time)
    created_by: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "release_id": self.release_id,
            "target_id": self.target_id,
            "adapter": self.adapter,
            "steps": list(self.steps),
            "health_checks": list(self.health_checks),
            "rollback_release_id": self.rollback_release_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DeploymentPlan":
        return cls(
            plan_id=str(d.get("plan_id") or ""),
            project_id=str(d.get("project_id") or ""),
            release_id=str(d.get("release_id") or ""),
            target_id=str(d.get("target_id") or ""),
            adapter=str(d.get("adapter") or "dry_run"),
            steps=list(d.get("steps") or []),
            health_checks=list(d.get("health_checks") or []),
            rollback_release_id=str(d.get("rollback_release_id") or ""),
            created_at=float(d.get("created_at") or 0.0),
            created_by=str(d.get("created_by") or ""),
            metadata=dict(d.get("metadata") or {}),
        )

    @staticmethod
    def new(
        project_id: str,
        release_id: str,
        target_id: str,
        *,
        adapter: str = "dry_run",
        created_by: str = "",
        rollback_release_id: str = "",
    ) -> "DeploymentPlan":
        return DeploymentPlan(
            plan_id="dp_" + uuid.uuid4().hex[:12],
            project_id=project_id,
            release_id=release_id,
            target_id=target_id,
            adapter=adapter,
            created_by=created_by,
            rollback_release_id=rollback_release_id,
            steps=[{"action": "verify_artifacts"}, {"action": "deploy"}, {"action": "health_check"}],
        )


@dataclass
class Deployment:
    """Record of a deployment execution."""

    deployment_id: str
    plan_id: str
    project_id: str
    release_id: str
    target_id: str
    status: DeploymentStatus = DeploymentStatus.PLANNED
    started_at: float = 0.0
    finished_at: float = 0.0
    authorized_by: str = ""
    error: str = ""
    audit_refs: List[str] = field(default_factory=list)
    health_results: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "deployment_id": self.deployment_id,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "release_id": self.release_id,
            "target_id": self.target_id,
            "status": self.status.value if isinstance(self.status, DeploymentStatus) else str(self.status),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "authorized_by": self.authorized_by,
            "error": self.error,
            "audit_refs": list(self.audit_refs),
            "health_results": dict(self.health_results),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Deployment":
        status_raw = str(d.get("status") or "planned").lower()
        try:
            status = DeploymentStatus(status_raw)
        except ValueError:
            status = DeploymentStatus.PLANNED
        return cls(
            deployment_id=str(d.get("deployment_id") or ""),
            plan_id=str(d.get("plan_id") or ""),
            project_id=str(d.get("project_id") or ""),
            release_id=str(d.get("release_id") or ""),
            target_id=str(d.get("target_id") or ""),
            status=status,
            started_at=float(d.get("started_at") or 0.0),
            finished_at=float(d.get("finished_at") or 0.0),
            authorized_by=str(d.get("authorized_by") or ""),
            error=str(d.get("error") or ""),
            audit_refs=list(d.get("audit_refs") or []),
            health_results=dict(d.get("health_results") or {}),
            created_at=float(d.get("created_at") or 0.0),
            metadata=dict(d.get("metadata") or {}),
        )

    @staticmethod
    def from_plan(plan: DeploymentPlan, *, authorized_by: str = "") -> "Deployment":
        return Deployment(
            deployment_id="dep_" + uuid.uuid4().hex[:12],
            plan_id=plan.plan_id,
            project_id=plan.project_id,
            release_id=plan.release_id,
            target_id=plan.target_id,
            authorized_by=authorized_by,
            status=DeploymentStatus.DRY_RUN if plan.adapter == "dry_run" else DeploymentStatus.PLANNED,
        )
