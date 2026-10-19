"""Policy & Scheduling control plane tests."""

from __future__ import annotations

import pytest

from mods.policy_scheduling.schema import INITIAL_DRAFT, ActivationMode, PolicyStatus
from mods.policy_scheduling.service import PolicyService
from mods.policy_scheduling.store import ConcurrentModificationError
from mods.policy_scheduling.multiflow_adapter import MultiFlowAdapter, MultiFlowAvailability


@pytest.fixture
def svc():
    return PolicyService()


def test_initial_preview_matches_spec(svc):
    st = svc.get_status()
    assert st["preview"]["latency_preference"] == 65
    assert st["preview"]["load_balancing_preference"] == 75
    assert st["preview"]["energy_efficiency_preference"] == 30
    assert st["preview"]["recovery_strategy"] == "balanced"
    assert st["preview"]["activation_mode"] == "shadow"
    assert st["active_version_id"] is None
    assert st["initial_draft"] == INITIAL_DRAFT


def test_preview_does_not_activate(svc):
    svc.update_preview({"latency_preference": 10})
    assert svc.get_status()["active_version_id"] is None
    assert svc.get_status()["preview"]["latency_preference"] == 10


def test_invalid_fields_rejected(svc):
    with pytest.raises(ValueError):
        svc.update_preview({"secret_backdoor": True})
    with pytest.raises(Exception):
        svc.update_preview({"latency_preference": 999})


def test_save_draft_immutable_versions(svc):
    svc.update_preview({"latency_preference": 40})
    d1 = svc.save_draft()
    assert d1.status == PolicyStatus.DRAFT
    sim = svc.simulate(workers=[{"node_id": "w1", "capabilities": ["mining"], "metadata": {}}])
    assert sim.side_effect_free is True
    v = svc.validate_draft()
    assert v.validation_ok is not None
    svc.request_activation(actor="operator", approved=True)
    active = svc.store.get_version(svc.store.active_version_id())
    assert active is not None
    with pytest.raises(ValueError):
        svc.store.put_version(active.model_copy(update={"notes": "tamper"}))


def test_simulation_no_dispatch(svc):
    svc.save_draft()
    sim = svc.simulate(workers=[])
    assert sim.side_effect_free is True
    assert svc.get_status()["active_version_id"] is None


def test_shadow_activation_records_without_claiming_live_dispatch(svc):
    svc.update_preview({"activation_mode": "shadow"})
    svc.save_draft()
    svc.simulate(workers=[{"node_id": "w1", "capabilities": [], "metadata": {}}])
    svc.validate_draft()
    result = svc.request_activation(actor="operator", approved=True)
    assert result["ok"] is True
    assert result.get("live_execution_changed") is False
    assert result["mode"] == "shadow"
    assert svc.store.active_version_id() is not None


def test_activation_concurrency_conflict(svc):
    svc.save_draft()
    svc.simulate(workers=[])
    svc.validate_draft()
    r1 = svc.request_activation(actor="operator", approved=True)
    assert r1["ok"]
    svc.update_preview({"latency_preference": 11})
    svc.save_draft()
    svc.simulate(workers=[])
    svc.validate_draft()
    r2 = svc.request_activation(actor="operator", approved=True, expected_active="stale-id")
    assert r2["ok"] is False
    assert r2.get("active_unchanged") is True


def test_rollback_creates_new_version(svc):
    svc.save_draft()
    svc.simulate(workers=[])
    svc.validate_draft()
    svc.request_activation(actor="operator", approved=True)
    active = svc.store.active_version_id()
    svc.update_preview({"latency_preference": 5})
    svc.save_draft()
    svc.simulate(workers=[])
    svc.validate_draft()
    svc.request_activation(actor="operator", approved=True)
    new_active = svc.store.active_version_id()
    assert new_active != active
    rb = svc.rollback(active, actor="operator", reason="test rollback")
    assert rb["ok"] is True
    assert rb["source_version_id"] == active
    assert rb["active_version_id"] != active
    versions = svc.list_versions()
    assert len(versions) >= 3


def test_quarantined_workers_excluded_from_snapshot(svc):
    snap = svc.adapter.collect_snapshot(
        workers=[
            {"node_id": "good", "capabilities": ["mining"], "metadata": {}},
            {"node_id": "bad", "capabilities": ["mining"], "metadata": {}},
        ],
        quarantined={"bad"},
        revoked=set(),
    )
    ids = {r["id"] for r in snap["resources"]}
    assert "good" in ids
    assert "bad" not in ids


def test_multiflow_disabled_by_default(svc):
    assert svc.adapter.availability in (
        MultiFlowAvailability.DISABLED,
        MultiFlowAvailability.PACKAGE_MISSING,
    )
    st = svc.adapter.status()
    assert st["execution_enabled"] is False


def test_unknown_security_fields_rejected(svc):
    with pytest.raises(ValueError):
        svc.update_preview({"activation_mode": "shadow", "grant_root": True})
