"""Tests for Aurora ecosystem control plane foundation.

Uses deterministic fake adapters only. Does not claim real hardware.
"""

from __future__ import annotations

import time
from typing import Any, Dict

import pytest

from control import (
    ActionDescriptor,
    ActionOutcome,
    ActionRequest,
    ActionResult,
    ActionSensitivity,
    AdapterManifest,
    Capability,
    CapabilityStatus,
    ControlPlane,
    ControlPlaneConfig,
    DesiredState,
    EcosystemAdapter,
    EntityRegistration,
    EntityType,
    NullAdapter,
    ObservedState,
    OperationalState,
    compute_registration_hash,
)


class FakeEchoAdapter(EcosystemAdapter):
    """Test double: echoes parameters on a single reversible action."""

    def __init__(self, adapter_id: str = "fake.echo"):
        self._id = adapter_id
        self.calls = []

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id=self._id,
            entity_type=EntityType.SOFTWARE_SERVICE,
            capabilities=[
                Capability(
                    name="echo",
                    status=CapabilityStatus.DECLARED,
                    operations=["echo"],
                )
            ],
            read_operations=["health"],
            actions=[
                ActionDescriptor(
                    name="echo",
                    sensitivity=ActionSensitivity.REVERSIBLE,
                    idempotent=True,
                    timeout_s=5.0,
                    authorization_scopes=["echo:write"],
                )
            ],
        )

    def health(self) -> Dict[str, Any]:
        return {"adapter_id": self._id, "status": "ok", "timestamp": time.time()}

    def read(self, operation: str, *, parameters=None) -> Dict[str, Any]:
        if operation == "health":
            return self.health()
        raise NotImplementedError(operation)

    def execute(self, request: ActionRequest) -> ActionResult:
        self.calls.append(request)
        return ActionResult(
            request_id=request.request_id,
            outcome=ActionOutcome.SUCCEEDED,
            entity_id=request.entity_id,
            action=request.action,
            message="echoed",
            result={"echo": request.parameters},
            authorized=True,
            completed_at=time.time(),
        )


def _entity(entity_id: str = "svc-1", adapter_id: str = "fake.echo") -> EntityRegistration:
    return EntityRegistration(
        entity_id=entity_id,
        entity_type=EntityType.SOFTWARE_SERVICE,
        adapter_id=adapter_id,
        capabilities=[
            Capability(name="echo", status=CapabilityStatus.DECLARED, operations=["echo"])
        ],
        registration_source="test",
    )


def test_entity_registration_and_stable_identity():
    plane = ControlPlane()
    reg = plane.register_entity(_entity())
    assert reg.entity_id == "svc-1"
    assert reg.content_hash
    reg2 = plane.register_entity(_entity())
    assert reg2.content_hash == reg.content_hash
    assert plane.get_entity("svc-1") is not None


def test_registration_requires_ids():
    plane = ControlPlane()
    with pytest.raises(ValueError, match="entity_id"):
        plane.register_entity(
            EntityRegistration(entity_id="", entity_type=EntityType.VIEWER, adapter_id="x")
        )
    with pytest.raises(ValueError, match="adapter_id"):
        plane.register_entity(
            EntityRegistration(entity_id="e1", entity_type=EntityType.VIEWER, adapter_id="")
        )


def test_heartbeat_and_staleness():
    plane = ControlPlane(ControlPlaneConfig(stale_after_s=1.0))
    plane.register_entity(_entity())
    ent = plane.get_entity("svc-1")
    ent.last_seen = time.time() - 5.0
    listed = plane.list_entities()
    assert listed[0].operational_state in (OperationalState.STALE, OperationalState.DISCONNECTED)
    plane.heartbeat("svc-1", health="healthy")
    assert plane.get_entity("svc-1").operational_state == OperationalState.HEALTHY


def test_capability_verification_distinct_from_declared():
    plane = ControlPlane()
    plane.register_entity(_entity())
    ent = plane.get_entity("svc-1")
    assert ent.capabilities[0].status == CapabilityStatus.DECLARED
    assert plane.registry.mark_capability_verified("svc-1", "echo")
    ent = plane.get_entity("svc-1")
    assert ent.capabilities[0].status == CapabilityStatus.VERIFIED
    assert ent.capabilities[0].last_verified_at is not None


def test_null_adapter_observation_only():
    adapter = NullAdapter()
    m = adapter.manifest()
    assert m.actions == []
    assert "health" in m.read_operations
    h = adapter.health()
    assert h["status"] == "ok"
    result = adapter.execute(ActionRequest(action="anything", entity_id="x"))
    assert result.outcome == ActionOutcome.DENIED


def test_unsupported_action_rejected():
    plane = ControlPlane(ControlPlaneConfig(require_auth_for_actions=False))
    fake = FakeEchoAdapter()
    plane.register_adapter(fake)
    plane.register_entity(_entity())
    result = plane.submit_action(
        ActionRequest(action="not_a_real_action", entity_id="svc-1"),
        authorized=True,
    )
    assert result.outcome == ActionOutcome.DENIED
    assert "unsupported" in result.message


def test_adapter_version_in_manifest():
    m = NullAdapter().manifest()
    d = m.to_dict()
    assert d["schema_id"] == "aurora.ecosystem.adapter"
    assert d["protocol_version"]


def test_desired_vs_observed_reconciliation_readonly():
    plane = ControlPlane()
    plane.register_entity(_entity())
    plane.request_desired(DesiredState(entity_id="svc-1", key="mode", value="run"))
    plane.report_observed(ObservedState(entity_id="svc-1", key="mode", value="idle"))
    eff = plane.reconcile("svc-1", "mode", can_execute=False)
    assert eff.desired == "run"
    assert eff.observed == "idle"
    assert eff.outcome == ActionOutcome.REQUESTED


def test_desired_matches_observed():
    plane = ControlPlane()
    plane.request_desired(DesiredState(entity_id="svc-1", key="mode", value="run"))
    plane.report_observed(ObservedState(entity_id="svc-1", key="mode", value="run"))
    eff = plane.reconcile("svc-1", "mode")
    assert eff.outcome == ActionOutcome.SUCCEEDED


def test_idempotent_desired_state():
    plane = ControlPlane()
    a = plane.request_desired(
        DesiredState(entity_id="svc-1", key="mode", value="run", idempotency_key="idem-1")
    )
    b = plane.request_desired(
        DesiredState(entity_id="svc-1", key="mode", value="stop", idempotency_key="idem-1")
    )
    assert a.request_id == b.request_id
    assert b.value == "run"


def test_unauthorized_action_denied():
    plane = ControlPlane(ControlPlaneConfig(require_auth_for_actions=True))
    fake = FakeEchoAdapter()
    plane.register_adapter(fake)
    plane.register_entity(_entity())
    result = plane.submit_action(
        ActionRequest(action="echo", entity_id="svc-1", parameters={"x": 1}),
        authorized=False,
    )
    assert result.outcome == ActionOutcome.DENIED
    assert result.authorized is False
    assert len(fake.calls) == 0


def test_authorized_action_succeeds():
    plane = ControlPlane(ControlPlaneConfig(require_auth_for_actions=True))
    fake = FakeEchoAdapter()
    plane.register_adapter(fake)
    plane.register_entity(_entity())
    result = plane.submit_action(
        ActionRequest(action="echo", entity_id="svc-1", parameters={"x": 1}),
        authorized=True,
    )
    assert result.outcome == ActionOutcome.SUCCEEDED
    assert result.result["echo"]["x"] == 1
    assert len(fake.calls) == 1


def test_quarantined_entity_denied():
    plane = ControlPlane(ControlPlaneConfig(require_auth_for_actions=False))
    fake = FakeEchoAdapter()
    plane.register_adapter(fake)
    plane.register_entity(_entity())
    plane.registry.quarantine("svc-1")
    result = plane.submit_action(
        ActionRequest(action="echo", entity_id="svc-1"),
        authorized=True,
    )
    assert result.outcome == ActionOutcome.DENIED


def test_expired_request_times_out():
    plane = ControlPlane(ControlPlaneConfig(require_auth_for_actions=False))
    fake = FakeEchoAdapter()
    plane.register_adapter(fake)
    plane.register_entity(_entity())
    result = plane.submit_action(
        ActionRequest(
            action="echo",
            entity_id="svc-1",
            expires_at=time.time() - 10,
        ),
        authorized=True,
    )
    assert result.outcome == ActionOutcome.TIMED_OUT


def test_unknown_entity_fails():
    plane = ControlPlane()
    result = plane.submit_action(
        ActionRequest(action="echo", entity_id="nope"),
        authorized=True,
    )
    assert result.outcome == ActionOutcome.FAILED
    assert "unknown entity" in result.message


def test_audit_log_records_lifecycle():
    plane = ControlPlane()
    plane.register_entity(_entity())
    log = plane.audit_log()
    assert any(e["event_type"] == "entity_registered" for e in log)
    for entry in log:
        assert "password" not in entry
        assert "api_key" not in entry


def test_status_surface():
    plane = ControlPlane()
    plane.register_entity(_entity())
    st = plane.status()
    assert st["control_plane_version"]
    assert st["entity_count"] == 1
    assert st["adapter_count"] >= 1


def test_readonly_without_execution_adapter():
    plane = ControlPlane()
    plane.register_entity(
        EntityRegistration(
            entity_id="viewer-1",
            entity_type=EntityType.VIEWER,
            adapter_id="aurora.null",
            registration_source="test",
        )
    )
    plane.report_observed(ObservedState(entity_id="viewer-1", key="connected", value=True))
    obs = plane.get_observed("viewer-1")
    assert len(obs) == 1
    assert obs[0].value is True
    result = plane.submit_action(
        ActionRequest(action="reboot", entity_id="viewer-1"),
        authorized=True,
    )
    assert result.outcome == ActionOutcome.DENIED


def test_compute_registration_hash_stable():
    a = _entity()
    b = _entity()
    assert compute_registration_hash(a) == compute_registration_hash(b)
    a.health = "degraded"
    a.last_seen = 999999.0
    assert compute_registration_hash(a) == compute_registration_hash(b)
