"""Desired, observed, and effective state for the Aurora control plane.

Never equates transport delivery with successful execution.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .adapter import ActionOutcome


class StateKind(str, Enum):
    DESIRED = "desired"
    OBSERVED = "observed"
    EFFECTIVE = "effective"


@dataclass
class DesiredState:
    """What an authorized operator or policy requests."""

    entity_id: str
    key: str
    value: Any
    request_id: str = ""
    requested_by: str = ""
    created_at: float = 0.0
    expires_at: Optional[float] = None
    idempotency_key: str = ""
    version: int = 1

    def __post_init__(self):
        if not self.request_id:
            self.request_id = str(uuid.uuid4())
        if not self.idempotency_key:
            self.idempotency_key = self.request_id
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "kind": StateKind.DESIRED.value,
            "entity_id": self.entity_id,
            "key": self.key,
            "value": self.value,
            "request_id": self.request_id,
            "requested_by": self.requested_by,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "idempotency_key": self.idempotency_key,
            "version": self.version,
        }


@dataclass
class ObservedState:
    """What a connected project or device actually reports."""

    entity_id: str
    key: str
    value: Any
    observed_at: float = 0.0
    source_adapter: str = ""
    confidence: str = "reported"  # reported | inferred | stale
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self.observed_at:
            self.observed_at = time.time()

    def to_dict(self) -> dict:
        return {
            "kind": StateKind.OBSERVED.value,
            "entity_id": self.entity_id,
            "key": self.key,
            "value": self.value,
            "observed_at": self.observed_at,
            "source_adapter": self.source_adapter,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass
class EffectiveState:
    """Result of reconciliation between desired and observed."""

    entity_id: str
    key: str
    desired: Optional[Any] = None
    observed: Optional[Any] = None
    effective: Optional[Any] = None
    outcome: ActionOutcome = ActionOutcome.UNKNOWN
    message: str = ""
    reconciled_at: float = 0.0
    request_id: str = ""

    def __post_init__(self):
        if not self.reconciled_at:
            self.reconciled_at = time.time()

    def to_dict(self) -> dict:
        return {
            "kind": StateKind.EFFECTIVE.value,
            "entity_id": self.entity_id,
            "key": self.key,
            "desired": self.desired,
            "observed": self.observed,
            "effective": self.effective,
            "outcome": self.outcome.value if isinstance(self.outcome, ActionOutcome) else str(self.outcome),
            "message": self.message,
            "reconciled_at": self.reconciled_at,
            "request_id": self.request_id,
        }


class StateStore:
    """Simple in-memory desired/observed state store with idempotency."""

    def __init__(self):
        self._desired: Dict[str, DesiredState] = {}  # idempotency_key -> DesiredState
        self._observed: Dict[str, ObservedState] = {}  # f"{entity_id}:{key}" -> ObservedState
        self._by_entity_desired: Dict[str, List[str]] = {}

    def set_desired(self, state: DesiredState) -> DesiredState:
        # Idempotent: same key returns prior record
        existing = self._desired.get(state.idempotency_key)
        if existing is not None:
            return existing
        self._desired[state.idempotency_key] = state
        self._by_entity_desired.setdefault(state.entity_id, []).append(state.idempotency_key)
        return state

    def get_desired(self, entity_id: str, key: Optional[str] = None) -> List[DesiredState]:
        keys = self._by_entity_desired.get(entity_id, [])
        out = [self._desired[k] for k in keys if k in self._desired]
        if key is not None:
            out = [s for s in out if s.key == key]
        return out

    def set_observed(self, state: ObservedState) -> ObservedState:
        slot = f"{state.entity_id}:{state.key}"
        self._observed[slot] = state
        return state

    def get_observed(self, entity_id: str, key: Optional[str] = None) -> List[ObservedState]:
        out = []
        prefix = f"{entity_id}:"
        for slot, state in self._observed.items():
            if slot.startswith(prefix):
                if key is None or state.key == key:
                    out.append(state)
        out.sort(key=lambda s: s.key)
        return out

    def reconcile(
        self,
        entity_id: str,
        key: str,
        *,
        can_execute: bool = False,
    ) -> EffectiveState:
        """Produce effective state from latest desired + observed.

        Read-only by default (can_execute=False): reports gap without acting.
        """
        desired_list = self.get_desired(entity_id, key)
        observed_list = self.get_observed(entity_id, key)
        desired = desired_list[-1] if desired_list else None
        observed = observed_list[-1] if observed_list else None

        if desired is None and observed is None:
            return EffectiveState(
                entity_id=entity_id,
                key=key,
                outcome=ActionOutcome.UNKNOWN,
                message="no desired or observed state",
            )

        if desired is None:
            return EffectiveState(
                entity_id=entity_id,
                key=key,
                observed=observed.value if observed else None,
                effective=observed.value if observed else None,
                outcome=ActionOutcome.SUCCEEDED,
                message="observation only; no desired state",
            )

        if observed is not None and observed.value == desired.value:
            return EffectiveState(
                entity_id=entity_id,
                key=key,
                desired=desired.value,
                observed=observed.value,
                effective=observed.value,
                outcome=ActionOutcome.SUCCEEDED,
                message="desired matches observed",
                request_id=desired.request_id,
            )

        if not can_execute:
            return EffectiveState(
                entity_id=entity_id,
                key=key,
                desired=desired.value,
                observed=observed.value if observed else None,
                effective=observed.value if observed else None,
                outcome=ActionOutcome.REQUESTED,
                message="desired differs from observed; execution not authorized in this path",
                request_id=desired.request_id,
            )

        # Execution path is deliberately narrow: caller must supply a real adapter.
        return EffectiveState(
            entity_id=entity_id,
            key=key,
            desired=desired.value,
            observed=observed.value if observed else None,
            effective=None,
            outcome=ActionOutcome.ACCEPTED,
            message="accepted for execution by authorized path",
            request_id=desired.request_id,
        )
