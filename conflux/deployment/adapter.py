"""Deployment adapter interface and dry-run implementation."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict

from conflux.models.deployment import Deployment, DeploymentPlan, DeploymentStatus
from conflux.models.release import Release


class DeploymentAdapter(ABC):
    name: str = "abstract"

    @abstractmethod
    def execute(self, plan: DeploymentPlan, deployment: Deployment, release: Release) -> Deployment:
        ...


class DryRunDeploymentAdapter(DeploymentAdapter):
    """Records intent without performing host or remote changes."""

    name = "dry_run"

    def execute(self, plan: DeploymentPlan, deployment: Deployment, release: Release) -> Deployment:
        deployment.status = DeploymentStatus.DRY_RUN
        deployment.started_at = time.time()
        deployment.health_results = {
            "dry_run": True,
            "release_id": release.release_id,
            "release_version": release.version,
            "target_id": plan.target_id,
            "steps_simulated": [s.get("action") for s in plan.steps],
            "message": "no changes applied",
        }
        deployment.finished_at = time.time()
        return deployment
