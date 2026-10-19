"""Versioned cross-repo contract envelopes.

Schema IDs align with CANtheon chimera-compatibility.json where applicable.
Missing schema / incompatible major / malformed security fields → explicit error.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

CONTRACT_CATALOG: Dict[str, str] = {
    "cantheon.metafield_boundary": "0.3.0",
    "metafield.evidence_lineage": "1.0",
    "tensorgate.lineage": "1.0",
    "multiflow.scheduling_api": "1.0.0",
    "multiflow.decision_evidence": "0.1.0",
    "aurora.mesh.evidence": "0.1.0",
    "aurora.execution": "1.0.0",
}


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class HealthStatus(BaseModel):
    schema_id: str = "aurora.cross_repo.health"
    schema_version: str = "1.0.0"
    healthy: bool = True
    components: Dict[str, Any] = Field(default_factory=dict)
    contracts: Dict[str, str] = Field(default_factory=lambda: dict(CONTRACT_CATALOG))
    detail: str = ""


class SchedulingRequestEnvelope(BaseModel):
    """Aurora → MultiFlow request envelope (maps to multiflow.scheduling_api)."""

    schema_id: str = "multiflow.scheduling_api"
    schema_version: str = "1.0.0"
    request_id: str = Field(default_factory=lambda: _new_id("areq"))
    correlation_id: str = Field(default_factory=lambda: _new_id("acorr"))
    problem: Dict[str, Any] = Field(default_factory=dict)
    preferences: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    snapshot_version: Optional[str] = None
    expected_snapshot_version: Optional[str] = None
    policy_version_id: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _major(cls, v: str) -> str:
        if (v or "0").split(".")[0] != "1":
            raise ValueError(f"incompatible multiflow.scheduling_api major: {v}")
        return v


class SchedulingPlanEnvelope(BaseModel):
    schema_id: str = "multiflow.scheduling_api"
    schema_version: str = "1.0.0"
    status: str = "UNAVAILABLE"
    correlation_id: str = ""
    admitted_plan: Optional[Dict[str, Any]] = None
    proposed_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    evidence: Optional[Dict[str, Any]] = None
    solver_identity: str = ""
    duration_ms: float = 0.0
    error: Optional[str] = None


class ExecutionRequest(BaseModel):
    schema_id: str = "aurora.execution"
    schema_version: str = "1.0.0"
    execution_id: str = Field(default_factory=lambda: _new_id("exec"))
    plan: Dict[str, Any] = Field(default_factory=dict)
    policy_version_id: Optional[str] = None
    correlation_id: str = ""
    snapshot_version: Optional[str] = None
    mode: str = "shadow"  # shadow | approval | controlled
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class ExecutionAcknowledgement(BaseModel):
    schema_id: str = "aurora.execution"
    schema_version: str = "1.0.0"
    execution_id: str = ""
    accepted: bool = False
    dispatched: bool = False
    mode: str = "shadow"
    reason: str = ""
    ts: float = Field(default_factory=time.time)
    evidence_hash: Optional[str] = None
