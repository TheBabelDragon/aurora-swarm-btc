"""Optional MultiFlow client for Aurora.

Uses multiflow.api.SchedulingApi when importable. Never treats a validated
plan as execution authorization — callers must obtain AEGIS approval separately.
"""

from __future__ import annotations

import logging
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from .contracts import SchedulingPlanEnvelope, SchedulingRequestEnvelope

logger = logging.getLogger("aurora.cross_repo.multiflow")


class MultiFlowClientStatus(str, Enum):
    AVAILABLE = "available"
    DISABLED = "disabled"
    PACKAGE_MISSING = "package_missing"
    ERROR = "error"


def _enabled() -> bool:
    return os.getenv("AURORA_MULTIFLOW_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def _bootstrap_vendor() -> None:
    root = Path(__file__).resolve().parents[2] / "vendor"
    if root.is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))


class MultiFlowClient:
    def __init__(self) -> None:
        self._api = None
        self._error: Optional[str] = None
        self._load()

    def _load(self) -> None:
        _bootstrap_vendor()
        try:
            from multiflow.api import SchedulingApi  # type: ignore

            self._api = SchedulingApi()
            self._error = None
        except Exception as e:
            self._api = None
            self._error = str(e)
            logger.info("MultiFlow SchedulingApi unavailable: %s", e)

    @property
    def status(self) -> MultiFlowClientStatus:
        if not _enabled():
            return MultiFlowClientStatus.DISABLED
        if self._api is None:
            return MultiFlowClientStatus.PACKAGE_MISSING
        return MultiFlowClientStatus.AVAILABLE

    def health(self) -> Dict[str, Any]:
        if self._api is None:
            return {
                "status": self.status.value,
                "enabled": _enabled(),
                "error": self._error,
            }
        h = self._api.health()
        return {
            "status": self.status.value,
            "enabled": _enabled(),
            "multiflow": h.model_dump() if hasattr(h, "model_dump") else dict(h),
        }

    def schedule(self, envelope: SchedulingRequestEnvelope) -> SchedulingPlanEnvelope:
        if not _enabled():
            return SchedulingPlanEnvelope(
                status="UNAVAILABLE",
                correlation_id=envelope.correlation_id,
                error="AURORA_MULTIFLOW_ENABLED is off",
            )
        if self._api is None:
            return SchedulingPlanEnvelope(
                status="UNAVAILABLE",
                correlation_id=envelope.correlation_id,
                error=f"multiflow unavailable: {self._error}",
            )
        try:
            from multiflow.api import SchedulingRequest  # type: ignore

            req = SchedulingRequest(
                request_id=envelope.request_id,
                correlation_id=envelope.correlation_id,
                problem=envelope.problem,
                preferences=envelope.preferences,
                evidence_refs=envelope.evidence_refs,
                snapshot_version=envelope.snapshot_version,
                expected_snapshot_version=envelope.expected_snapshot_version,
            )
            resp = self._api.schedule(req)
            return SchedulingPlanEnvelope(
                status=resp.status.value if hasattr(resp.status, "value") else str(resp.status),
                correlation_id=resp.correlation_id,
                admitted_plan=resp.admitted_plan,
                proposed_candidates=list(resp.proposed_candidates or []),
                blocking_reasons=list(resp.blocking_reasons or []),
                evidence=resp.evidence,
                solver_identity=resp.solver_identity,
                duration_ms=resp.duration_ms,
                error=resp.error,
            )
        except Exception as e:
            return SchedulingPlanEnvelope(
                status="SOLVER_ERROR",
                correlation_id=envelope.correlation_id,
                error=str(e),
            )
