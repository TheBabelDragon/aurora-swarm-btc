"""Conflux v0.1 isolated tests."""

from __future__ import annotations

import pytest

from conflux.config import ConfluxConfig
from conflux.models.changeset import ChangesetStatus
from conflux.models.deployment import DeploymentStatus
from conflux.models.release import ReleaseStatus
from conflux.service import ConfluxService
from conflux.storage.persistence import MemoryStore


@pytest.fixture
def svc() -> ConfluxService:
    cfg = ConfluxConfig(runner_enabled=False, local_deploy_enabled=False)
    return ConfluxService(config=cfg, store=MemoryStore())


def test_status(svc: ConfluxService):
    st = svc.status()
    assert st["service"] == "conflux"
    assert st["version"] == "0.1.1"
    assert "project_registry" in st["capabilities"]
    assert "evidence" in st


def test_project_and_source(svc: ConfluxService):
    p = svc.create_project("demo", description="test", created_by="tester")
    assert p.project_id.startswith("prj_")
    assert svc.get_project(p.project_id) is not None
    src = svc.add_source(p.project_id, remote_url="https://example.com/repo.git", default_branch="main")
    assert src is not None
    assert src.kind == "git"
    assert len(svc.list_sources(p.project_id)) == 1


def test_changeset_conflict_and_approve(svc: ConfluxService):
    p = svc.create_project("cs-demo")
    src = svc.add_source(p.project_id, remote_url="https://example.com/r.git")
    assert src
    base = "abc123"
    cs1 = svc.create_changeset(
        p.project_id,
        src.source_id,
        base,
        author="agent-a",
        intent="change file",
        files=[{"path": "a.py", "change_type": "modify", "content_hash_after": "h1"}],
    )
    cs2 = svc.create_changeset(
        p.project_id,
        src.source_id,
        base,
        author="agent-b",
        intent="also change file",
        files=[{"path": "a.py", "change_type": "modify", "content_hash_after": "h2"}],
    )
    assert cs1 and cs2
    result = svc.reconcile_changeset(cs1.changeset_id, peer_ids=[cs2.changeset_id])
    assert result["ok"] is False
    assert "conflicts" in result
    cs1b = svc.get_changeset(cs1.changeset_id)
    assert cs1b and cs1b.status == ChangesetStatus.CONFLICTING


def test_reconcile_clean_then_approve(svc: ConfluxService):
    p = svc.create_project("clean")
    src = svc.add_source(p.project_id, remote_url="https://example.com/r.git")
    assert src
    cs = svc.create_changeset(
        p.project_id,
        src.source_id,
        "rev1",
        author="a",
        files=[{"path": "b.py", "change_type": "add", "content_hash_after": "x"}],
    )
    assert cs
    r = svc.reconcile_changeset(cs.changeset_id)
    assert r["ok"] is True
    svc.changes.mark_verified(cs.changeset_id, status="passed")
    ap = svc.approve_changeset(cs.changeset_id, approved_by="reviewer")
    assert ap["ok"] is True
    assert ap["changeset"]["status"] == "approved"


def test_build_skipped_when_runner_disabled(svc: ConfluxService):
    p = svc.create_project("build-demo")
    rec = svc.create_build(p.project_id, "rev1", run=True)
    assert rec is not None
    assert rec.status.value == "skipped"
    assert rec.error == "runner_disabled"


def test_build_safe_runner_when_enabled():
    cfg = ConfluxConfig(runner_enabled=True)
    svc = ConfluxService(config=cfg, store=MemoryStore())
    p = svc.create_project("build-on")
    rec = svc.create_build(p.project_id, "rev1", instructions=["noop"], run=True)
    assert rec is not None
    assert rec.status.value == "succeeded"
    assert len(rec.output_artifact_ids) >= 1
    arts = svc.list_artifacts(project_id=p.project_id)
    assert len(arts) >= 1
    assert arts[0].content_hash


def test_release_immutable_promote(svc: ConfluxService):
    p = svc.create_project("rel")
    rel = svc.create_release(p.project_id, "0.1.0", "rev1", created_by="dev")
    assert rel and rel.status == ReleaseStatus.CANDIDATE
    h = rel.content_hash
    pr = svc.promote_release(rel.release_id, promoted_by="ops")
    assert pr["ok"] is True
    rel2 = svc.get_release(rel.release_id)
    assert rel2 and rel2.status == ReleaseStatus.PROMOTED
    assert rel2.content_hash == h


def test_dry_run_deployment(svc: ConfluxService):
    p = svc.create_project("dep")
    rel = svc.create_release(p.project_id, "1.0.0", "rev1")
    assert rel
    svc.promote_release(rel.release_id, promoted_by="ops")
    plan = svc.plan_deployment(p.project_id, rel.release_id, "target-local", adapter="dry_run")
    assert plan and plan.adapter == "dry_run"
    result = svc.execute_deployment(plan.plan_id, authorized_by="ops")
    assert result["ok"] is True
    dep = result["deployment"]
    assert dep["status"] == DeploymentStatus.DRY_RUN.value


def test_unauthorized_non_dry_run_forced_to_dry_or_fail(svc: ConfluxService):
    p = svc.create_project("sec")
    rel = svc.create_release(p.project_id, "1.0.0", "rev1")
    assert rel
    plan = svc.plan_deployment(p.project_id, rel.release_id, "host-1", adapter="local")
    assert plan
    assert plan.adapter == "dry_run"


def test_persistence_recovery():
    store = MemoryStore()
    svc = ConfluxService(store=store)
    p = svc.create_project("persist")
    snap = store.snapshot()
    store2 = MemoryStore()
    store2.restore(snap)
    svc2 = ConfluxService(store=store2)
    assert svc2.get_project(p.project_id) is not None


def test_idempotent_project_ids_unique(svc: ConfluxService):
    a = svc.create_project("x")
    b = svc.create_project("x")
    assert a.project_id != b.project_id
