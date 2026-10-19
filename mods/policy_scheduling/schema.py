"""Policy schema — preferences vs hard constraints.

Numeric preferences rank feasible plans; they never make an infeasible or
unauthorized plan admissible. Hard constraints are enforced separately
(worker health, capacity, AEGIS authorization, route eligibility, etc.).
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class RecoveryStrategy(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    CONSERVATIVE = "conservative"


class ActivationMode(str, Enum):
    SHADOW = "shadow"
    APPROVAL = "approval"
    CONTROLLED = "controlled"


class PolicyStatus(str, Enum):
    DRAFT = "draft"
    SIMULATED = "simulated"
    VALIDATED = "validated"
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


# Unsaved preview values only — must NOT auto-activate
INITIAL_DRAFT: Dict[str, Any] = {
    "latency_preference": 65,
    "load_balancing_preference": 75,
    "energy_efficiency_preference": 30,
    "recovery_strategy": "balanced",
    "activation_mode": "shadow",
}


def _new_version_id() -> str:
    return f"pol-{uuid.uuid4().hex[:12]}"


class PolicyPreferences(BaseModel):
    """Optimization preferences (0–100). Not permissions or safety settings."""

    latency_preference: int = Field(default=65, ge=0, le=100)
    load_balancing_preference: int = Field(default=75, ge=0, le=100)
    energy_efficiency_preference: int = Field(default=30, ge=0, le=100)
    recovery_strategy: RecoveryStrategy = RecoveryStrategy.BALANCED
    activation_mode: ActivationMode = ActivationMode.SHADOW

    @field_validator("recovery_strategy", mode="before")
    @classmethod
    def _rs(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.lower()
        return v

    @field_validator("activation_mode", mode="before")
    @classmethod
    def _am(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.lower()
        return v

    def normalized_weights(self) -> Dict[str, float]:
        """Normalize preference triad to sum 1.0 for objective ranking."""
        raw = [
            max(0, self.latency_preference),
            max(0, self.load_balancing_preference),
            max(0, self.energy_efficiency_preference),
        ]
        s = sum(raw) or 1.0
        return {
            "latency": raw[0] / s,
            "load_balancing": raw[1] / s,
            "energy_efficiency": raw[2] / s,
        }


class PolicyDocument(BaseModel):
    """Immutable policy version once status leaves draft editing."""

    version_id: str = Field(default_factory=_new_version_id)
    status: PolicyStatus = PolicyStatus.DRAFT
    preferences: PolicyPreferences = Field(default_factory=lambda: PolicyPreferences(**INITIAL_DRAFT))
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    created_by: str = "operator"
    parent_version_id: Optional[str] = None
    simulation_id: Optional[str] = None
    validation_ok: Optional[bool] = None
    validation_summary: str = ""
    notes: str = ""
    expected_active_version: Optional[str] = None  # optimistic concurrency token

    def mark(self, status: PolicyStatus) -> "PolicyDocument":
        return self.model_copy(update={"status": status, "updated_at": time.time()})


class SimulationResult(BaseModel):
    simulation_id: str = Field(default_factory=lambda: f"sim-{uuid.uuid4().hex[:12]}")
    policy_version_id: str
    snapshot_version: str
    ts: float = Field(default_factory=time.time)
    side_effect_free: bool = True
    multiflow_available: bool = False
    solver_identity: str = "none"
    admissible: bool = False
    status: str = "unavailable"  # admissible | no_complete_solution | unavailable | error
    current_plan: List[Dict[str, Any]] = Field(default_factory=list)
    proposed_plan: List[Dict[str, Any]] = Field(default_factory=list)
    added: List[Dict[str, Any]] = Field(default_factory=list)
    removed: List[Dict[str, Any]] = Field(default_factory=list)
    changed: List[Dict[str, Any]] = Field(default_factory=list)
    constraint_violations: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    objective_estimate: Dict[str, float] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    evidence_ref: Optional[str] = None


class AuditEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: f"pae-{uuid.uuid4().hex[:10]}")
    ts: float = Field(default_factory=time.time)
    action: str
    actor: str = "operator"
    policy_version_id: Optional[str] = None
    prior_active_version: Optional[str] = None
    outcome: str = "ok"
    detail: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
