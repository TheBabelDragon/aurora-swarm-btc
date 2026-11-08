"""Evidence Integrity bridge records for Conflux lifecycle."""

from __future__ import annotations

from conflux.config import ConfluxConfig
from conflux.service import ConfluxService
from conflux.storage.persistence import MemoryStore
from conflux.verification.evidence_bridge import EvidenceBridge


def test_evidence_on_project_build_release_deploy():
    bridge = EvidenceBridge(node_id="test")
    svc = ConfluxService(
        config=ConfluxConfig(runner_enabled=True),
        store=MemoryStore(),
        evidence=bridge,
    )
    p = svc.create_project("ev-demo", created_by="tester")
    assert bridge.available
    assert len(bridge.chain_hashes()) >= 1

    src = svc.add_source(p.project_id, remote_url="https://example.com/r.git")
    assert src
    cs = svc.create_changeset(
        p.project_id,
        src.source_id,
        "rev1",
        author="a",
        files=[{"path": "x.py", "change_type": "add", "content_hash_after": "h"}],
    )
    assert cs
    svc.changes.mark_verified(cs.changeset_id, status="passed")
    ap = svc.approve_changeset(cs.changeset_id, approved_by="rev")
    assert ap.get("ok")

    b = svc.create_build(p.project_id, "rev1", run=True, actor_id="tester")
    assert b is not None
    rel = svc.create_release(p.project_id, "1.0.0", "rev1", build_id=b.build_id, created_by="tester")
    assert rel
    pr = svc.promote_release(rel.release_id, promoted_by="ops")
    assert pr.get("ok")

    plan = svc.plan_deployment(p.project_id, rel.release_id, "t1", created_by="ops")
    assert plan
    dep = svc.execute_deployment(plan.plan_id, authorized_by="ops")
    assert dep.get("ok")

    chain = bridge.chain_hashes()
    assert len(chain) >= 6
    # parent linkage: later objects reference earlier hashes via bridge
    st = svc.status()
    assert st["evidence"]["count"] == len(chain)
    assert st["version"] == "0.1.1"


def test_evidence_export_boundary():
    bridge = EvidenceBridge()
    if not bridge.available:
        return
    bridge.record("test.event", entity_id="e1", outcome="ok")
    exported = bridge.export()
    assert isinstance(exported, list)
    assert len(exported) >= 1
    assert "content_hash" in exported[0]
