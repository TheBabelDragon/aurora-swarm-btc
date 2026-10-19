"""Policy & Scheduling Rules API — mounted on the Aurora dashboard app."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora.policy.routes")


def _auth(request: Request) -> Optional[JSONResponse]:
    try:
        from dashboard.comms_security import check_dashboard_auth

        ok, detail = check_dashboard_auth(request.headers)
        if ok:
            return None
        return JSONResponse(
            {"ok": False, "error": "unauthorized", "detail": detail or "X-API-Key required"},
            status_code=401,
        )
    except Exception:
        return None


def install_policy_routes(app: Any, *, get_comms: Optional[Callable[[], Any]] = None) -> None:
    from .service import get_policy_service, start_policy_service

    def _svc():
        svc = get_policy_service()
        if svc is None:
            comms = get_comms() if get_comms else None
            svc = start_policy_service(comms)
        return svc

    @app.get("/policy/status")
    def policy_status(request: Request):
        denied = _auth(request)
        if denied:
            return denied
        return _svc().get_status()

    @app.get("/policy/versions")
    def policy_versions(request: Request):
        denied = _auth(request)
        if denied:
            return denied
        return {"versions": _svc().list_versions()}

    @app.get("/policy/audit")
    def policy_audit(request: Request, limit: int = 50):
        denied = _auth(request)
        if denied:
            return denied
        return {"audit": _svc().list_audit(limit=min(limit, 200))}

    @app.post("/policy/preview")
    async def policy_preview(request: Request):
        denied = _auth(request)
        if denied:
            return denied
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            preview = _svc().update_preview(body if isinstance(body, dict) else {})
            return {"ok": True, "preview": preview, "active_unchanged": True}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/policy/draft/save")
    async def policy_draft_save(request: Request):
        denied = _auth(request)
        if denied:
            return denied
        try:
            body = await request.json()
        except Exception:
            body = {}
        actor = (body or {}).get("actor") or "operator"
        try:
            if body and any(k in body for k in ("latency_preference", "load_balancing_preference")):
                _svc().update_preview(body)
            doc = _svc().save_draft(actor=actor)
            return {"ok": True, "draft": doc.model_dump(), "active_unchanged": True}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/policy/draft/discard")
    async def policy_draft_discard(request: Request):
        denied = _auth(request)
        if denied:
            return denied
        _svc().discard_draft()
        return {"ok": True, "preview": _svc().get_status()["preview"]}

    @app.post("/policy/simulate")
    async def policy_simulate(request: Request):
        denied = _auth(request)
        if denied:
            return denied
        try:
            body = await request.json()
        except Exception:
            body = {}
        actor = (body or {}).get("actor") or "operator"
        try:
            sim = _svc().simulate(actor=actor)
            return {"ok": True, "simulation": sim.model_dump(), "side_effect_free": True}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/policy/validate")
    async def policy_validate(request: Request):
        denied = _auth(request)
        if denied:
            return denied
        try:
            body = await request.json()
        except Exception:
            body = {}
        actor = (body or {}).get("actor") or "operator"
        try:
            doc = _svc().validate_draft(actor=actor)
            return {"ok": True, "policy": doc.model_dump()}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/policy/activate")
    async def policy_activate(request: Request):
        denied = _auth(request)
        if denied:
            return denied
        try:
            body = await request.json()
        except Exception:
            body = {}
        actor = (body or {}).get("actor") or "operator"
        approved = bool((body or {}).get("approved"))
        expected = (body or {}).get("expected_active_version")
        try:
            result = _svc().request_activation(
                actor=actor, expected_active=expected, approved=approved
            )
            code = 200 if result.get("ok") else 403
            return JSONResponse(result, status_code=code)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/policy/rollback")
    async def policy_rollback(request: Request):
        denied = _auth(request)
        if denied:
            return denied
        try:
            body = await request.json()
        except Exception:
            body = {}
        target = (body or {}).get("version_id")
        if not target:
            return JSONResponse({"ok": False, "error": "version_id required"}, status_code=400)
        actor = (body or {}).get("actor") or "operator"
        reason = (body or {}).get("reason") or ""
        expected = (body or {}).get("expected_active_version")
        try:
            result = _svc().rollback(
                target, actor=actor, reason=reason, expected_active=expected
            )
            code = 200 if result.get("ok") else 403
            return JSONResponse(result, status_code=code)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.get("/policy/compare")
    def policy_compare(request: Request, a: str = "", b: str = ""):
        denied = _auth(request)
        if denied:
            return denied
        if not a or not b:
            return JSONResponse({"ok": False, "error": "a and b version ids required"}, status_code=400)
        try:
            return {"ok": True, **_svc().compare(a, b)}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    logger.info("Policy & Scheduling routes mounted at /policy/*")
