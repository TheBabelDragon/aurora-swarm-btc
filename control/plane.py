"""Aurora Ecosystem Control Plane facade.

Coordinates registry, adapters, desired/observed state, and audit-friendly
outcomes. Does not become a runtime dependency of firmware projects.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .adapter import (
    ActionOutcome,
    ActionRequest,
    ActionResult,
    AdapterManifest,
    EcosystemAdapter,
    NullAdapter,
)
from .registry import (
    CapabilityRegistry,
    EntityRegistration,
    EntityType,
    OperationalState,
)
from .state import DesiredState, EffectiveState, ObservedState, StateStore


CONTROL_PLANE_VERSION = "0.1.0"


@dataclass
class ControlPlaneConfig:
    stale_after_s: float = 120.0
    require_auth_for_actions: bool = True


class ControlPlane:
    """Top-level control-plane service.

    Read-only observation works without any execution adapter.
    Actions require an explicit adapter and (when configured) authorization.
    """

    def __init__(self, config: Optional[ControlPlaneConfig] = None):
        self.config = config or ControlPlaneConfig()
        self.registry = CapabilityRegistry(stale_after_s=self.config.stale_after_s)
        self.state = StateStore()
        self._adapters: Dict[str, EcosystemAdapter] = {}
        self._audit: List[Dict[str, Any]] = []
        # Built-in observation adapter
        self.register_adapter(NullAdapter(adapter_id="aurora.null"))

    # --- adapters ----------------------------------------------------------

    def register_adapter(self, adapter: EcosystemAdapter) -> AdapterManifest:
        manifest = adapter.manifest()
        self._adapters[manifest.adapter_id] = adapter
        self._audit_event(
            "adapter_registered",
            adapter_id=manifest.adapter_id,
            protocol_version=manifest.protocol_version,
        )
        return manifest

    def get_adapter(self, adapter_id: str) -> Optional[EcosystemAdapter]:
        return self._adapters.get(adapter_id)

    def list_adapters(self) -> List[AdapterManifest]:
        return [a.manifest() for a in self._adapters.values()]

    # --- entity registration -----------------------------------------------

    def register_entity(self, reg: EntityRegistration) -> EntityRegistration:
        stored = self.registry.register(reg)
        self._audit_event(
            "entity_registered",
            entity_id=stored.entity_id,
            entity_type=stored.entity_type.value,
            adapter_id=stored.adapter_id,
            content_hash=stored.content_hash,
        )
        return stored

    def heartbeat(self, entity_id: str, *, health: Optional[str] = None) -> Optional[EntityRegistration]:
        return self.registry.heartbeat(entity_id, health=health)

    def list_entities(
        self,
        *,
        entity_type: Optional[EntityType] = None,
        include_stale: bool = True,
    ) -> List[EntityRegistration]:
        return self.registry.list(entity_type=entity_type, include_stale=include_stale)

    def get_entity(self, entity_id: str) -> Optional[EntityRegistration]:
        return self.registry.get(entity_id)

    # --- observation -------------------------------------------------------

    def report_observed(self, state: ObservedState) -> ObservedState:
        stored = self.state.set_observed(state)
        # Touch registry heartbeat if known
        self.registry.heartbeat(state.entity_id)
        return stored

    def get_observed(self, entity_id: str, key: Optional[str] = None) -> List[ObservedState]:
        return self.state.get_observed(entity_id, key)

    # --- desired state -----------------------------------------------------

    def request_desired(self, state: DesiredState) -> DesiredState:
        stored = self.state.set_desired(state)
        self._audit_event(
            "desired_state_requested",
            entity_id=stored.entity_id,
            key=stored.key,
            request_id=stored.request_id,
            requested_by=stored.requested_by,
        )
        return stored

    def reconcile(
        self,
        entity_id: str,
        key: str,
        *,
        can_execute: bool = False,
    ) -> EffectiveState:
        return self.state.reconcile(entity_id, key, can_execute=can_execute)

    # --- actions -----------------------------------------------------------

    def submit_action(
        self,
        request: ActionRequest,
        *,
        authorized: bool = False,
        scopes: Optional[List[str]] = None,
    ) -> ActionResult:
        """Submit an action through the entity's adapter.

        Authorization is explicit: callers must pass authorized=True after
        consulting AEGIS-42 / policy. This plane does not auto-trust registration.
        """
        entity = self.registry.get(request.entity_id)
        if entity is None:
            result = ActionResult(
                request_id=request.request_id,
                outcome=ActionOutcome.FAILED,
                entity_id=request.entity_id,
                action=request.action,
                message="unknown entity",
                authorized=False,
            )
            self._audit_action(request, result)
            return result

        if entity.operational_state in (
            OperationalState.QUARANTINED,
            OperationalState.REVOKED,
        ):
            result = ActionResult(
                request_id=request.request_id,
                outcome=ActionOutcome.DENIED,
                entity_id=request.entity_id,
                action=request.action,
                message=f"entity is {entity.operational_state.value}",
                authorized=False,
            )
            self._audit_action(request, result)
            return result

        if self.config.require_auth_for_actions and not authorized:
            result = ActionResult(
                request_id=request.request_id,
                outcome=ActionOutcome.DENIED,
                entity_id=request.entity_id,
                action=request.action,
                message="action not authorized",
                authorized=False,
            )
            self._audit_action(request, result)
            return result

        if request.expires_at is not None and time.time() > request.expires_at:
            result = ActionResult(
                request_id=request.request_id,
                outcome=ActionOutcome.TIMED_OUT,
                entity_id=request.entity_id,
                action=request.action,
                message="request expired before execution",
                authorized=True,
            )
            self._audit_action(request, result)
            return result

        adapter = self._adapters.get(entity.adapter_id)
        if adapter is None:
            result = ActionResult(
                request_id=request.request_id,
                outcome=ActionOutcome.FAILED,
                entity_id=request.entity_id,
                action=request.action,
                message=f"no adapter registered for '{entity.adapter_id}'",
                authorized=True,
            )
            self._audit_action(request, result)
            return result

        # Check action is declared
        manifest = adapter.manifest()
        known_actions = {a.name for a in manifest.actions}
        if request.action not in known_actions:
            result = ActionResult(
                request_id=request.request_id,
                outcome=ActionOutcome.DENIED,
                entity_id=request.entity_id,
                action=request.action,
                message=f"unsupported action '{request.action}'",
                authorized=True,
            )
            self._audit_action(request, result)
            return result

        try:
            result = adapter.execute(request)
        except Exception as e:
            result = ActionResult(
                request_id=request.request_id,
                outcome=ActionOutcome.FAILED,
                entity_id=request.entity_id,
                action=request.action,
                message=str(e),
                authorized=True,
                completed_at=time.time(),
            )
        if result.completed_at is None and result.outcome in (
            ActionOutcome.SUCCEEDED,
            ActionOutcome.FAILED,
            ActionOutcome.DENIED,
            ActionOutcome.TIMED_OUT,
        ):
            result.completed_at = time.time()
        self._audit_action(request, result)
        return result

    # --- audit / status ----------------------------------------------------

    def status(self) -> Dict[str, Any]:
        entities = self.registry.list()
        return {
            "control_plane_version": CONTROL_PLANE_VERSION,
            "entity_count": len(entities),
            "adapter_count": len(self._adapters),
            "stale_after_s": self.config.stale_after_s,
            "require_auth_for_actions": self.config.require_auth_for_actions,
            "entities_by_state": _count_by_state(entities),
        }

    def audit_log(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self._audit[-limit:])

    def _audit_event(self, event_type: str, **fields: Any) -> None:
        entry = {
            "event_type": event_type,
            "timestamp": time.time(),
            **fields,
        }
        # Never put credentials into audit
        for secret_key in ("password", "secret", "token", "api_key", "credential"):
            entry.pop(secret_key, None)
        self._audit.append(entry)

    def _audit_action(self, request: ActionRequest, result: ActionResult) -> None:
        self._audit_event(
            "action_result",
            request_id=request.request_id,
            entity_id=request.entity_id,
            action=request.action,
            outcome=result.outcome.value if hasattr(result.outcome, "value") else str(result.outcome),
            authorized=result.authorized,
            message=result.message,
        )


def _count_by_state(entities: List[EntityRegistration]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for e in entities:
        key = e.operational_state.value if hasattr(e.operational_state, "value") else str(e.operational_state)
        counts[key] = counts.get(key, 0) + 1
    return counts
