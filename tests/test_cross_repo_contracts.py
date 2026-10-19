"""Cross-repo contract tests (no live sibling imports required)."""

from __future__ import annotations

import pytest

from mods.cross_repo.contracts import (
    CONTRACT_CATALOG,
    ExecutionAcknowledgement,
    ExecutionRequest,
    SchedulingRequestEnvelope,
)
from mods.cross_repo.evidence_bridge import ingest_decision_evidence, link_evidence_chain
from mods.cross_repo.multiflow_client import MultiFlowClient, MultiFlowClientStatus


def test_contract_catalog_has_chimera_entries():
    assert "cantheon.metafield_boundary" in CONTRACT_CATALOG
    assert "multiflow.scheduling_api" in CONTRACT_CATALOG
    assert "aurora.mesh.evidence" in CONTRACT_CATALOG


def test_scheduling_request_rejects_major_mismatch():
    with pytest.raises(Exception):
        SchedulingRequestEnvelope(schema_version="2.0.0", problem={"x": 1})


def test_execution_request_shadow_default():
    req = ExecutionRequest(plan={"assignments": []})
    assert req.mode == "shadow"
    ack = ExecutionAcknowledgement(
        execution_id=req.execution_id,
        accepted=True,
        dispatched=False,
        mode="shadow",
        reason="shadow never dispatches",
    )
    assert ack.dispatched is False


def test_multiflow_client_disabled_by_default():
    client = MultiFlowClient()
    assert client.status in (
        MultiFlowClientStatus.DISABLED,
        MultiFlowClientStatus.PACKAGE_MISSING,
    )
    env = SchedulingRequestEnvelope(problem={})
    plan = client.schedule(env)
    assert plan.status == "UNAVAILABLE"


def test_link_evidence_chain():
    chain = link_evidence_chain(
        observation_ref={"id": "obs-1"},
        decision_ref={"decision_id": "dec-1"},
        policy_version_id="pol-abc",
        authorization={"allowed": True},
    )
    assert chain["chain_complete"] is True
    roles = [r.get("role") for r in chain["evidence_refs"]]
    assert "aurora.policy_version" in roles


def test_ingest_decision_evidence_roundtrip():
    h = ingest_decision_evidence(
        {
            "schema_id": "multiflow.decision_evidence",
            "schema_version": "0.1.0",
            "decision_id": "dec-test",
            "outcome_status": "ADMITTED",
            "admitted_candidate_id": "c1",
        },
        node_id="test-node",
    )
    assert h is not None
    assert len(h) == 64  # sha256 hex
