"""Aurora-side tests: Octopie boundary is fail-closed and isolated."""

from __future__ import annotations

import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comms.octopie.boundary import OctopieBoundary, BoundaryConfig
from comms.octopie.contract import CONTRACT_VERSION


def _admit(node_id="n1", decided_at=None, expires_at=None, version=CONTRACT_VERSION):
    decided_at = decided_at if decided_at is not None else time.time()
    return {
        "node_id": node_id,
        "outcome": "admit",
        "trust_outcome": "admitted_active",
        "reason_code": "admitted",
        "decided_at": decided_at,
        "policy_version": "1",
        "contract_version": version,
        "correlation_id": f"c-{node_id}-{decided_at}",
        "expires_at": expires_at,
        "capabilities": ["worker"],
    }


def test_disabled_by_default():
    b = OctopieBoundary()
    assert b.config.mode == "disabled"
    ok, reason = b.ingest_decision(_admit())
    assert ok is False and reason == "octopie_disabled"
    assert b.is_trusted("n1") is False


def test_aurora_functions_without_octopie():
    b = OctopieBoundary(BoundaryConfig(mode="disabled"))
    assert b.transport_success_grants_trust() is False
    assert b.trusted_nodes() == []
    assert b.status().to_dict()["octopie_enabled"] is False


def test_observe_only_validates_but_does_not_grant():
    b = OctopieBoundary(BoundaryConfig(mode="observe_only"))
    ok, reason = b.ingest_decision(_admit())
    assert ok is True and reason == "observed_not_enforced"
    assert b.is_trusted("n1") is False


def test_enforce_accepts_valid_admit():
    b = OctopieBoundary(BoundaryConfig(mode="enforce"))
    ok, reason = b.ingest_decision(_admit("n1"))
    assert ok is True and reason == "admitted"
    assert b.is_trusted("n1") is True


def test_malformed_rejected():
    b = OctopieBoundary(BoundaryConfig(mode="enforce"))
    ok, _ = b.ingest_decision({"node_id": "x"})
    assert ok is False and b.is_trusted("x") is False


def test_incompatible_version_rejected():
    b = OctopieBoundary(BoundaryConfig(mode="enforce"))
    ok, reason = b.ingest_decision(_admit(version="octopie-aurora/9.9"))
    assert ok is False
    assert "incompatible" in reason or "version" in reason


def test_expired_decision_rejected():
    b = OctopieBoundary(BoundaryConfig(mode="enforce"))
    past = time.time() - 1000
    ok, reason = b.ingest_decision(_admit(decided_at=past, expires_at=past + 10))
    assert ok is False and reason == "decision_expired"


def test_revocation_removes_trust():
    b = OctopieBoundary(BoundaryConfig(mode="enforce"))
    b.ingest_decision(_admit("n1"))
    assert b.is_trusted("n1") is True
    ok, _ = b.ingest_revocation({
        "node_id": "n1", "revoked_at": time.time(), "reason_code": "compromise",
        "policy_version": "1", "contract_version": CONTRACT_VERSION,
    })
    assert ok is True and b.is_trusted("n1") is False
    ok2, reason2 = b.ingest_decision(_admit("n1", decided_at=time.time()))
    assert ok2 is False and reason2 == "node_revoked"


def test_duplicate_correlation_idempotent():
    b = OctopieBoundary(BoundaryConfig(mode="enforce"))
    payload = _admit("n1")
    ok1, _ = b.ingest_decision(payload)
    ok2, reason2 = b.ingest_decision(payload)
    assert ok1 and ok2 and reason2 == "duplicate_idempotent"
    assert len(b.trusted_nodes()) == 1


def test_transport_success_never_grants_trust():
    b = OctopieBoundary(BoundaryConfig(mode="enforce"))
    assert b.transport_success_grants_trust() is False
    assert b.is_trusted("mesh-peer-99") is False


def test_outage_mode_no_extra_privileges():
    b = OctopieBoundary(BoundaryConfig(mode="disabled"))
    b.ingest_decision(_admit("n1"))
    assert b.is_trusted("n1") is False
    assert b.status().to_dict()["decisions_rejected"] >= 1


def test_status_exposes_diagnostics_without_secrets():
    b = OctopieBoundary(BoundaryConfig(mode="observe_only"))
    b.ingest_decision(_admit())
    d = b.status().to_dict()
    assert "contract_version" in d
    assert "token" not in str(d).lower()
