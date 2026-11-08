"""Conflux service — lifecycle orchestration.

Standalone subsystem. Reuses Asset Fabric, Evidence Integrity, AEGIS-42,
CommsLayer, and Control Plane via explicit interfaces; does not duplicate them.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from conflux.config import ConfluxConfig
from conflux.coordination.changes import ChangesetCoordinator
from conflux.build.runner import SafeTestRunner
from conflux.deployment.adapter import DryRunDeploymentAdapter
from conflux.models.artifact import ArtifactManifest, ArtifactRef
from conflux.models.build import BuildManifest, BuildRecord, BuildStatus
from conflux.models.changeset import Changeset, FileChange
from conflux.models.deployment import Deployment, DeploymentPlan, DeploymentStatus
from conflux.models.evidence import EvidenceRef, ProvenanceRecord
from conflux.models.project import Project, SourceRef
from conflux.models.release import Release, ReleaseStatus
from conflux.models.source import SourceRevision
from conflux.source.git_adapter import GitSourceAdapter
from conflux.storage.persistence import ConfluxStore, MemoryStore

logger = logging.getLogger("conflux.service")


class ConfluxService:
    """Primary entry point for Conflux operations."""

    def __init__(
        self,
        *,
        config: Optional[ConfluxConfig] = None,
        store: Optional[ConfluxStore] = None,
    ) -> None:
        self.config = config or ConfluxConfig.from_env()
        self.store = store or MemoryStore()
        self.git = GitSourceAdapter()
        self.changes = ChangesetCoordinator(self.store)
        self.runner = SafeTestRunner()
        self.deploy_adapter = DryRunDeploymentAdapter()
        self._started_at = time.time()

    # ── status ──────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "service": "conflux",
            "version": "0.1.0",
            "schema_id": "aurora.conflux",
            "runner_enabled": self.config.runner_enabled,
            "local_deploy_enabled": self.config.local_deploy_enabled,
            "storage": type(self.store).__name__,
            "uptime_s": round(time.time() - self._started_at, 1),
            "capabilities": [
                "project_registry",
                "git_source",
                "changesets",
                "reconciliation",
                "build_records",
                "dry_run_deployment",
                "immutable_releases",
            ],
        }

    # ── projects ────────────────────────────────────────────────────────

    def create_project(self, name: str, *, description: str = "", created_by: str = "") -> Project:
        p = Project.new(name, description=description, created_by=created_by)
        self.store.put("projects", p.project_id, p.to_dict())
        return p

    def get_project(self, project_id: str) -> Optional[Project]:
        d = self.store.get("projects", project_id)
        return Project.from_dict(d) if d else None

    def list_projects(self, *, limit: int = 50) -> List[Project]:
        return [Project.from_dict(v) for v in self.store.list_values("projects", limit=limit)]

    def add_source(
        self,
        project_id: str,
        *,
        kind: str = "git",
        remote_url: str = "",
        local_path: str = "",
        default_branch: str = "main",
    ) -> Optional[SourceRef]:
        p = self.get_project(project_id)
        if not p:
            return None
        sid = SourceRef.make_id(kind, remote_url, local_path)
        src = SourceRef(
            source_id=sid,
            kind=kind,
            remote_url=remote_url,
            local_path=local_path,
            default_branch=default_branch,
        )
        p.sources.append(src)
        p.content_hash = Project._hash(p)
        self.store.put("projects", p.project_id, p.to_dict())
        self.store.put("sources", sid, src.to_dict())
        return src

    def list_sources(self, project_id: str) -> List[SourceRef]:
        p = self.get_project(project_id)
        return list(p.sources) if p else []

    def resolve_revision(
        self,
        project_id: str,
        source_id: str,
        *,
        ref: str = "HEAD",
    ) -> Optional[SourceRevision]:
        p = self.get_project(project_id)
        if not p:
            return None
        src = next((s for s in p.sources if s.source_id == source_id), None)
        if not src:
            return None
        rev = self.git.resolve_revision(src, project_id=project_id, ref=ref)
        if rev:
            self.store.put("revisions", rev.revision_id, rev.to_dict())
        return rev

    # ── changesets ──────────────────────────────────────────────────────

    def create_changeset(
        self,
        project_id: str,
        source_id: str,
        base_revision_id: str,
        *,
        author: str = "",
        agent_id: str = "",
        intent: str = "",
        files: Optional[List[dict]] = None,
    ) -> Optional[Changeset]:
        if not self.get_project(project_id):
            return None
        fcs = [FileChange.from_dict(f) for f in (files or [])]
        cs = Changeset.new(
            project_id,
            source_id,
            base_revision_id,
            author=author,
            agent_id=agent_id,
            intent=intent,
            files=fcs,
        )
        return self.changes.create(cs)

    def get_changeset(self, changeset_id: str) -> Optional[Changeset]:
        return self.changes.get(changeset_id)

    def list_changesets(self, **kwargs: Any) -> List[Changeset]:
        return self.changes.list(**kwargs)

    def reconcile_changeset(self, changeset_id: str, peer_ids: Optional[List[str]] = None) -> dict:
        return self.changes.reconcile(changeset_id, peer_ids=peer_ids)

    def approve_changeset(self, changeset_id: str, *, approved_by: str) -> dict:
        return self.changes.approve(changeset_id, approved_by=approved_by)

    # ── builds ──────────────────────────────────────────────────────────

    def create_build(
        self,
        project_id: str,
        source_revision_id: str,
        *,
        changeset_ids: Optional[List[str]] = None,
        instructions: Optional[List[str]] = None,
        run: bool = False,
    ) -> Optional[BuildRecord]:
        if not self.get_project(project_id):
            return None
        manifest = BuildManifest.new(
            project_id,
            source_revision_id,
            changeset_ids=changeset_ids,
            instructions=instructions or ["echo conflux-safe-build"],
        )
        self.store.put("build_manifests", manifest.manifest_id, manifest.to_dict())
        record = self.runner.execute(
            manifest,
            enabled=run and self.config.runner_enabled,
        )
        # Persist synthetic artifacts if any
        for ad in record.metadata.get("artifacts") or []:
            art = ArtifactRef.from_dict(ad)
            self.store.put("artifacts", art.artifact_id, art.to_dict())
        self.store.put("builds", record.build_id, record.to_dict())
        return record

    def get_build(self, build_id: str) -> Optional[BuildRecord]:
        d = self.store.get("builds", build_id)
        return BuildRecord.from_dict(d) if d else None

    def list_builds(self, *, project_id: str = "", limit: int = 50) -> List[BuildRecord]:
        out = []
        for v in self.store.list_values("builds", limit=limit * 2):
            b = BuildRecord.from_dict(v)
            if project_id and b.project_id != project_id:
                continue
            out.append(b)
            if len(out) >= limit:
                break
        return out

    def list_artifacts(self, *, project_id: str = "", limit: int = 50) -> List[ArtifactRef]:
        out = []
        for v in self.store.list_values("artifacts", limit=limit * 2):
            a = ArtifactRef.from_dict(v)
            if project_id and a.project_id != project_id:
                continue
            out.append(a)
            if len(out) >= limit:
                break
        return out

    def get_artifact(self, artifact_id: str) -> Optional[ArtifactRef]:
        d = self.store.get("artifacts", artifact_id)
        return ArtifactRef.from_dict(d) if d else None

    # ── releases ────────────────────────────────────────────────────────

    def create_release(
        self,
        project_id: str,
        version: str,
        source_revision_id: str,
        *,
        build_id: str = "",
        changeset_ids: Optional[List[str]] = None,
        created_by: str = "",
    ) -> Optional[Release]:
        if not self.get_project(project_id):
            return None
        rel = Release.new(
            project_id,
            version,
            source_revision_id,
            build_id=build_id,
            changeset_ids=changeset_ids,
            created_by=created_by,
        )
        self.store.put("releases", rel.release_id, rel.to_dict())
        return rel

    def get_release(self, release_id: str) -> Optional[Release]:
        d = self.store.get("releases", release_id)
        return Release.from_dict(d) if d else None

    def list_releases(self, *, project_id: str = "", limit: int = 50) -> List[Release]:
        out = []
        for v in self.store.list_values("releases", limit=limit * 2):
            r = Release.from_dict(v)
            if project_id and r.project_id != project_id:
                continue
            out.append(r)
            if len(out) >= limit:
                break
        return out

    def promote_release(self, release_id: str, *, promoted_by: str) -> dict:
        rel = self.get_release(release_id)
        if not rel:
            return {"ok": False, "error": "release_not_found"}
        if rel.status == ReleaseStatus.REVOKED:
            return {"ok": False, "error": "release_revoked"}
        if rel.status == ReleaseStatus.PROMOTED:
            return {"ok": False, "error": "already_promoted"}
        # Gate: prefer verified builds when present
        if rel.build_id:
            b = self.get_build(rel.build_id)
            if b and b.status not in (BuildStatus.SUCCEEDED, BuildStatus.SKIPPED):
                return {"ok": False, "error": "build_not_successful"}
        rel.status = ReleaseStatus.PROMOTED
        rel.promoted_at = time.time()
        rel.promoted_by = promoted_by
        self.store.put("releases", rel.release_id, rel.to_dict())
        return {"ok": True, "release": rel.to_dict()}

    # ── deployments ─────────────────────────────────────────────────────

    def plan_deployment(
        self,
        project_id: str,
        release_id: str,
        target_id: str,
        *,
        adapter: str = "dry_run",
        created_by: str = "",
        rollback_release_id: str = "",
    ) -> Optional[DeploymentPlan]:
        if not self.get_project(project_id) or not self.get_release(release_id):
            return None
        if adapter != "dry_run" and not self.config.local_deploy_enabled:
            adapter = "dry_run"
        plan = DeploymentPlan.new(
            project_id,
            release_id,
            target_id,
            adapter=adapter,
            created_by=created_by,
            rollback_release_id=rollback_release_id,
        )
        self.store.put("deployment_plans", plan.plan_id, plan.to_dict())
        return plan

    def execute_deployment(
        self,
        plan_id: str,
        *,
        authorized_by: str = "",
    ) -> dict:
        pd = self.store.get("deployment_plans", plan_id)
        if not pd:
            return {"ok": False, "error": "plan_not_found"}
        plan = DeploymentPlan.from_dict(pd)
        rel = self.get_release(plan.release_id)
        if not rel:
            return {"ok": False, "error": "release_not_found"}
        if rel.status not in (ReleaseStatus.PROMOTED, ReleaseStatus.VERIFIED, ReleaseStatus.CANDIDATE):
            return {"ok": False, "error": "release_not_eligible"}
        dep = Deployment.from_plan(plan, authorized_by=authorized_by)
        if plan.adapter == "dry_run":
            dep = self.deploy_adapter.execute(plan, dep, rel)
        else:
            dep.status = DeploymentStatus.FAILED
            dep.error = "non_dry_run_disabled_in_v0_1"
            dep.finished_at = time.time()
        self.store.put("deployments", dep.deployment_id, dep.to_dict())
        return {"ok": True, "deployment": dep.to_dict()}

    def get_deployment(self, deployment_id: str) -> Optional[Deployment]:
        d = self.store.get("deployments", deployment_id)
        return Deployment.from_dict(d) if d else None

    def list_deployments(self, *, project_id: str = "", limit: int = 50) -> List[Deployment]:
        out = []
        for v in self.store.list_values("deployments", limit=limit * 2):
            d = Deployment.from_dict(v)
            if project_id and d.project_id != project_id:
                continue
            out.append(d)
            if len(out) >= limit:
                break
        return out

    def rollback_deployment(
        self,
        deployment_id: str,
        *,
        authorized_by: str = "",
    ) -> dict:
        dep = self.get_deployment(deployment_id)
        if not dep:
            return {"ok": False, "error": "deployment_not_found"}
        pd = self.store.get("deployment_plans", dep.plan_id)
        if not pd:
            return {"ok": False, "error": "plan_not_found"}
        plan = DeploymentPlan.from_dict(pd)
        if not plan.rollback_release_id:
            return {"ok": False, "error": "no_rollback_release"}
        rb = self.get_release(plan.rollback_release_id)
        if not rb:
            return {"ok": False, "error": "rollback_release_not_found"}
        # Plan a dry-run rollback deployment
        rb_plan = self.plan_deployment(
            dep.project_id,
            plan.rollback_release_id,
            dep.target_id,
            adapter="dry_run",
            created_by=authorized_by,
        )
        if not rb_plan:
            return {"ok": False, "error": "rollback_plan_failed"}
        result = self.execute_deployment(rb_plan.plan_id, authorized_by=authorized_by)
        if result.get("ok"):
            dep.status = DeploymentStatus.ROLLED_BACK
            self.store.put("deployments", dep.deployment_id, dep.to_dict())
        return result

    # ── audit / provenance ──────────────────────────────────────────────

    def audit_log(self, *, limit: int = 50) -> List[dict]:
        """Lightweight local audit trail of stored entities."""
        entries = []
        for col in ("projects", "changesets", "builds", "releases", "deployments"):
            for v in self.store.list_values(col, limit=limit):
                entries.append({"collection": col, "id": v.get(f"{col[:-1]}_id") or v.get("project_id") or "", "record": v})
        return entries[:limit]
