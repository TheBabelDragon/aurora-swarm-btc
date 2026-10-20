"""Dashboard routes for the Aurora ecosystem control plane.

Read endpoints are public (same convention as /comms/status).
Mutations require dashboard API key when AURORA_DASHBOARD_API_KEY is set.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.control_ops")

_plane = None


def get_control_plane():
    """Lazy singleton ControlPlane for this process."""
    global _plane
    if _plane is None:
        from control.plane import ControlPlane, ControlPlaneConfig

        _plane = ControlPlane(ControlPlaneConfig(require_auth_for_actions=True))
        logger.info("ControlPlane initialized")
    return _plane


def _auth_ok(request: Request) -> tuple:
    try:
        from dashboard.comms_security import check_dashboard_auth
    except Exception:
        try:
            from comms_security import check_dashboard_auth
        except Exception:
            return True, None
    return check_dashboard_auth(request.headers)


def install_control_ops(app: Any, *, get_comms: Optional[Callable[[], Any]] = None):
    """Mount control-plane HTTP routes on the FastAPI app."""

    @app.get("/control/status")
    def control_status():
        plane = get_control_plane()
        st = plane.status()
        st["ok"] = True
        st["ts"] = time.time()
        return st

    @app.get("/control/entities")
    def control_list_entities(
        entity_type: Optional[str] = None,
        include_stale: bool = True,
    ):
        plane = get_control_plane()
        et = None
        if entity_type:
            from control.registry import EntityType

            try:
                et = EntityType(entity_type.lower())
            except ValueError:
                return JSONResponse(
                    {"ok": False, "error": f"unknown entity_type '{entity_type}'"},
                    status_code=400,
                )
        entities = plane.list_entities(entity_type=et, include_stale=include_stale)
        return {
            "ok": True,
            "count": len(entities),
            "entities": [e.to_dict() for e in entities],
            "ts": time.time(),
        }

    @app.get("/control/entities/{entity_id}")
    def control_get_entity(entity_id: str):
        plane = get_control_plane()
        ent = plane.get_entity(entity_id)
        if ent is None:
            return JSONResponse({"ok": False, "error": "entity not found"}, status_code=404)
        observed = [o.to_dict() for o in plane.get_observed(entity_id)]
        return {
            "ok": True,
            "entity": ent.to_dict(),
            "observed": observed,
            "ts": time.time(),
        }

    @app.post("/control/entities/register")
    async def control_register_entity(request: Request):
        ok, err = _auth_ok(request)
        if not ok:
            return JSONResponse({"ok": False, "error": err}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "body must be object"}, status_code=400)

        from control.registry import EntityRegistration

        try:
            reg = EntityRegistration.from_dict(body)
            stored = get_control_plane().register_entity(reg)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        return {"ok": True, "entity": stored.to_dict(), "ts": time.time()}

    @app.post("/control/entities/{entity_id}/heartbeat")
    async def control_heartbeat(entity_id: str, request: Request):
        ok, err = _auth_ok(request)
        if not ok:
            return JSONResponse({"ok": False, "error": err}, status_code=401)
        health = None
        try:
            body = await request.json()
            if isinstance(body, dict):
                health = body.get("health")
        except Exception:
            pass
        plane = get_control_plane()
        ent = plane.heartbeat(entity_id, health=health)
        if ent is None:
            return JSONResponse({"ok": False, "error": "entity not found"}, status_code=404)
        return {"ok": True, "entity": ent.to_dict(), "ts": time.time()}

    @app.get("/control/adapters")
    def control_list_adapters():
        plane = get_control_plane()
        manifests = plane.list_adapters()
        return {
            "ok": True,
            "count": len(manifests),
            "adapters": [m.to_dict() for m in manifests],
            "ts": time.time(),
        }

    @app.post("/control/desired")
    async def control_set_desired(request: Request):
        ok, err = _auth_ok(request)
        if not ok:
            return JSONResponse({"ok": False, "error": err}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "body must be object"}, status_code=400)

        from control.state import DesiredState

        entity_id = str(body.get("entity_id") or "").strip()
        key = str(body.get("key") or "").strip()
        if not entity_id or not key:
            return JSONResponse(
                {"ok": False, "error": "entity_id and key required"},
                status_code=400,
            )
        state = DesiredState(
            entity_id=entity_id,
            key=key,
            value=body.get("value"),
            requested_by=str(body.get("requested_by") or "dashboard"),
            idempotency_key=str(body.get("idempotency_key") or ""),
            expires_at=body.get("expires_at"),
        )
        stored = get_control_plane().request_desired(state)
        return {"ok": True, "desired": stored.to_dict(), "ts": time.time()}

    @app.post("/control/observed")
    async def control_report_observed(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "body must be object"}, status_code=400)

        from control.state import ObservedState

        entity_id = str(body.get("entity_id") or "").strip()
        key = str(body.get("key") or "").strip()
        if not entity_id or not key:
            return JSONResponse(
                {"ok": False, "error": "entity_id and key required"},
                status_code=400,
            )
        state = ObservedState(
            entity_id=entity_id,
            key=key,
            value=body.get("value"),
            source_adapter=str(body.get("source_adapter") or ""),
            confidence=str(body.get("confidence") or "reported"),
            evidence_refs=list(body.get("evidence_refs") or []),
        )
        stored = get_control_plane().report_observed(state)
        return {"ok": True, "observed": stored.to_dict(), "ts": time.time()}

    @app.get("/control/reconcile/{entity_id}")
    def control_reconcile(entity_id: str, key: str = "mode"):
        plane = get_control_plane()
        eff = plane.reconcile(entity_id, key, can_execute=False)
        return {"ok": True, "effective": eff.to_dict(), "ts": time.time()}

    @app.post("/control/actions")
    async def control_submit_action(request: Request):
        ok, err = _auth_ok(request)
        if not ok:
            return JSONResponse({"ok": False, "error": err}, status_code=401)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "error": "body must be object"}, status_code=400)

        from control.adapter import ActionRequest

        action = str(body.get("action") or "").strip()
        entity_id = str(body.get("entity_id") or "").strip()
        if not action or not entity_id:
            return JSONResponse(
                {"ok": False, "error": "action and entity_id required"},
                status_code=400,
            )
        req = ActionRequest(
            action=action,
            entity_id=entity_id,
            parameters=dict(body.get("parameters") or {}),
            requested_by=str(body.get("requested_by") or "dashboard"),
            idempotency_key=str(body.get("idempotency_key") or ""),
            correlation_id=str(body.get("correlation_id") or ""),
            expires_at=body.get("expires_at"),
        )
        result = get_control_plane().submit_action(req, authorized=True)
        status = 200
        if result.outcome.value == "denied":
            status = 403
        elif result.outcome.value == "failed":
            status = 400
        elif result.outcome.value == "timed_out":
            status = 408
        ok_flag = result.outcome.value in ("succeeded", "accepted", "executing", "requested")
        return JSONResponse(
            {"ok": ok_flag, "result": result.to_dict(), "ts": time.time()},
            status_code=status if not ok_flag else 200,
        )

    @app.get("/control/audit")
    def control_audit(limit: int = 50):
        plane = get_control_plane()
        limit = max(1, min(int(limit or 50), 500))
        return {
            "ok": True,
            "events": plane.audit_log(limit=limit),
            "ts": time.time(),
        }

    logger.info("control_ops mounted (/control/*)")
