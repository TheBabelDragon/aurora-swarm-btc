"""Conflux HTTP API — independently mounted under /conflux/*.

Never returns secrets. Accepted != succeeded for async-style operations.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("conflux.routes")


def _api_key_ok(x_api_key: Optional[str]) -> bool:
    expected = os.getenv("AURORA_DASHBOARD_API_KEY", "").strip()
    if not expected:
        return True  # open when unset (same convention as dashboard)
    return bool(x_api_key) and x_api_key == expected


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    created_by: str = ""


class SourceCreate(BaseModel):
    kind: str = "git"
    remote_url: str = ""
    local_path: str = ""
    default_branch: str = "main"


class ChangesetCreate(BaseModel):
    project_id: str
    source_id: str
    base_revision_id: str
    author: str = ""
    agent_id: str = ""
    intent: str = ""
    files: list = Field(default_factory=list)


class ReconcileRequest(BaseModel):
    peer_ids: list = Field(default_factory=list)


class ApproveRequest(BaseModel):
    approved_by: str = Field(..., min_length=1)


class BuildCreate(BaseModel):
    project_id: str
    source_revision_id: str
    changeset_ids: list = Field(default_factory=list)
    instructions: list = Field(default_factory=list)
    run: bool = False


class ReleaseCreate(BaseModel):
    project_id: str
    version: str = Field(..., min_length=1)
    source_revision_id: str
    build_id: str = ""
    changeset_ids: list = Field(default_factory=list)
    created_by: str = ""


class PromoteRequest(BaseModel):
    promoted_by: str = Field(..., min_length=1)


class DeployPlanRequest(BaseModel):
    project_id: str
    release_id: str
    target_id: str
    adapter: str = "dry_run"
    created_by: str = ""
    rollback_release_id: str = ""


class DeployExecuteRequest(BaseModel):
    plan_id: str
    authorized_by: str = ""


class RollbackRequest(BaseModel):
    authorized_by: str = ""


def create_conflux_router(get_service: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/conflux", tags=["conflux"])

    def svc():
        return get_service()

    def require_key(x_api_key: Optional[str]) -> None:
        if not _api_key_ok(x_api_key):
            raise HTTPException(status_code=401, detail="invalid_or_missing_api_key")

    @router.get("/status")
    def status():
        return svc().status()

    @router.get("/projects")
    def list_projects(limit: int = Query(20, ge=1, le=100)):
        return {"projects": [p.to_dict() for p in svc().list_projects(limit=limit)]}

    @router.post("/projects")
    def create_project(body: ProjectCreate, x_api_key: Optional[str] = Header(None)):
        require_key(x_api_key)
        p = svc().create_project(body.name, description=body.description, created_by=body.created_by)
        return {"project": p.to_dict()}

    @router.get("/projects/{project_id}")
    def get_project(project_id: str):
        p = svc().get_project(project_id)
        if not p:
            raise HTTPException(404, "project_not_found")
        return {"project": p.to_dict()}

    @router.get("/projects/{project_id}/sources")
    def list_sources(project_id: str):
        return {"sources": [s.to_dict() for s in svc().list_sources(project_id)]}

    @router.post("/projects/{project_id}/sources")
    def add_source(project_id: str, body: SourceCreate, x_api_key: Optional[str] = Header(None)):
        require_key(x_api_key)
        src = svc().add_source(
            project_id,
            kind=body.kind,
            remote_url=body.remote_url,
            local_path=body.local_path,
            default_branch=body.default_branch,
        )
        if not src:
            raise HTTPException(404, "project_not_found")
        return {"source": src.to_dict()}

    @router.get("/changesets")
    def list_changesets(
        project_id: str = "",
        status: str = "",
        limit: int = Query(20, ge=1, le=100),
    ):
        return {
            "changesets": [
                c.to_dict()
                for c in svc().list_changesets(project_id=project_id, status=status, limit=limit)
            ]
        }

    @router.post("/changesets")
    def create_changeset(body: ChangesetCreate, x_api_key: Optional[str] = Header(None)):
        require_key(x_api_key)
        cs = svc().create_changeset(
            body.project_id,
            body.source_id,
            body.base_revision_id,
            author=body.author,
            agent_id=body.agent_id,
            intent=body.intent,
            files=body.files,
        )
        if not cs:
            raise HTTPException(404, "project_not_found")
        return {"changeset": cs.to_dict()}

    @router.get("/changesets/{changeset_id}")
    def get_changeset(changeset_id: str):
        cs = svc().get_changeset(changeset_id)
        if not cs:
            raise HTTPException(404, "changeset_not_found")
        return {"changeset": cs.to_dict()}

    @router.post("/changesets/{changeset_id}/reconcile")
    def reconcile(changeset_id: str, body: ReconcileRequest, x_api_key: Optional[str] = Header(None)):
        require_key(x_api_key)
        return svc().reconcile_changeset(changeset_id, peer_ids=body.peer_ids)

    @router.post("/changesets/{changeset_id}/approve")
    def approve(changeset_id: str, body: ApproveRequest, x_api_key: Optional[str] = Header(None)):
        require_key(x_api_key)
        return svc().approve_changeset(changeset_id, approved_by=body.approved_by)

    @router.post("/builds")
    def create_build(body: BuildCreate, x_api_key: Optional[str] = Header(None)):
        require_key(x_api_key)
        rec = svc().create_build(
            body.project_id,
            body.source_revision_id,
            changeset_ids=body.changeset_ids,
            instructions=body.instructions,
            run=body.run,
        )
        if not rec:
            raise HTTPException(404, "project_not_found")
        return {"build": rec.to_dict(), "accepted": True, "executed": rec.status.value != "skipped"}

    @router.get("/builds")
    def list_builds(project_id: str = "", limit: int = Query(20, ge=1, le=100)):
        return {"builds": [b.to_dict() for b in svc().list_builds(project_id=project_id, limit=limit)]}

    @router.get("/builds/{build_id}")
    def get_build(build_id: str):
        b = svc().get_build(build_id)
        if not b:
            raise HTTPException(404, "build_not_found")
        return {"build": b.to_dict()}

    @router.get("/artifacts")
    def list_artifacts(project_id: str = "", limit: int = Query(20, ge=1, le=100)):
        return {"artifacts": [a.to_dict() for a in svc().list_artifacts(project_id=project_id, limit=limit)]}

    @router.get("/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str):
        a = svc().get_artifact(artifact_id)
        if not a:
            raise HTTPException(404, "artifact_not_found")
        return {"artifact": a.to_dict()}

    @router.post("/releases")
    def create_release(body: ReleaseCreate, x_api_key: Optional[str] = Header(None)):
        require_key(x_api_key)
        rel = svc().create_release(
            body.project_id,
            body.version,
            body.source_revision_id,
            build_id=body.build_id,
            changeset_ids=body.changeset_ids,
            created_by=body.created_by,
        )
        if not rel:
            raise HTTPException(404, "project_not_found")
        return {"release": rel.to_dict()}

    @router.get("/releases")
    def list_releases(project_id: str = "", limit: int = Query(20, ge=1, le=100)):
        return {"releases": [r.to_dict() for r in svc().list_releases(project_id=project_id, limit=limit)]}

    @router.get("/releases/{release_id}")
    def get_release(release_id: str):
        r = svc().get_release(release_id)
        if not r:
            raise HTTPException(404, "release_not_found")
        return {"release": r.to_dict()}

    @router.post("/releases/{release_id}/promote")
    def promote(release_id: str, body: PromoteRequest, x_api_key: Optional[str] = Header(None)):
        require_key(x_api_key)
        return svc().promote_release(release_id, promoted_by=body.promoted_by)

    @router.post("/deployments/plan")
    def plan_deploy(body: DeployPlanRequest, x_api_key: Optional[str] = Header(None)):
        require_key(x_api_key)
        plan = svc().plan_deployment(
            body.project_id,
            body.release_id,
            body.target_id,
            adapter=body.adapter,
            created_by=body.created_by,
            rollback_release_id=body.rollback_release_id,
        )
        if not plan:
            raise HTTPException(404, "project_or_release_not_found")
        return {"plan": plan.to_dict()}

    @router.post("/deployments/execute")
    def exec_deploy(body: DeployExecuteRequest, x_api_key: Optional[str] = Header(None)):
        require_key(x_api_key)
        return svc().execute_deployment(body.plan_id, authorized_by=body.authorized_by)

    @router.get("/deployments")
    def list_deployments(project_id: str = "", limit: int = Query(20, ge=1, le=100)):
        return {
            "deployments": [
                d.to_dict() for d in svc().list_deployments(project_id=project_id, limit=limit)
            ]
        }

    @router.get("/deployments/{deployment_id}")
    def get_deployment(deployment_id: str):
        d = svc().get_deployment(deployment_id)
        if not d:
            raise HTTPException(404, "deployment_not_found")
        return {"deployment": d.to_dict()}

    @router.post("/deployments/{deployment_id}/rollback")
    def rollback(deployment_id: str, body: RollbackRequest, x_api_key: Optional[str] = Header(None)):
        require_key(x_api_key)
        return svc().rollback_deployment(deployment_id, authorized_by=body.authorized_by)

    @router.get("/audit")
    def audit(limit: int = Query(50, ge=1, le=200)):
        return {"entries": svc().audit_log(limit=limit)}

    return router
