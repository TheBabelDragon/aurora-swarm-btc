"""AEGIS-42 dashboard / API routes.

Reuses existing auth patterns. Does not expose secrets or private model outputs.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, status

logger = logging.getLogger("aurora.aegis42.routes")

router = APIRouter(prefix="/aegis", tags=["aegis-42"])


def _check_api_key(x_api_key: Optional[str] = None) -> None:
    expected = (os.getenv("AURORA_DASHBOARD_API_KEY") or "").strip()
    if not expected:
        return  # no key configured → open (same as rest of dashboard)
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or missing API key")


@router.get("/status")
def aegis_status(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    _check_api_key(x_api_key)
    from .core import get_aegis

    aegis = get_aegis()
    if aegis is None:
        return {"enabled": False, "running": False, "message": "AEGIS-42 not started"}
    return aegis.status()


@router.get("/events")
def aegis_recent_decisions(
    limit: int = 30,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    _check_api_key(x_api_key)
    from .core import get_aegis

    aegis = get_aegis()
    if aegis is None:
        return {"decisions": []}
    decisions = aegis.policy.recent_decisions(limit=min(limit, 100))
    return {"decisions": [d.model_dump() for d in decisions]}


@router.get("/audit")
def aegis_audit(
    limit: int = 30,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    _check_api_key(x_api_key)
    from .core import get_aegis

    aegis = get_aegis()
    if aegis is None:
        return {"records": [], "integrity": {"ok": False}}
    records = aegis.audit.recent(limit=min(limit, 100))
    integrity = aegis.audit.verify_integrity()
    return {
        "records": [r.model_dump() for r in records],
        "integrity": integrity,
    }


@router.get("/identities")
def aegis_identities(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    _check_api_key(x_api_key)
    from .core import get_aegis

    aegis = get_aegis()
    if aegis is None:
        return {"identities": []}
    ids = aegis.identity.list_identities()
    return {
        "identities": [
            {
                "identity_id": r.identity_id,
                "kind": r.kind,
                "trust_level": r.trust.trust_level,
                "capabilities": list(r.capabilities.keys()),
                "revoked": r.trust.revoked,
            }
            for r in ids
        ]
    }


@router.get("/containment")
def aegis_containment(
    limit: int = 20,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    _check_api_key(x_api_key)
    from .core import get_aegis

    aegis = get_aegis()
    if aegis is None:
        return {"actions": []}
    return {"actions": [r.model_dump() for r in aegis.containment.recent(limit=min(limit, 50))]}


def install_aegis_routes(app: Any) -> None:
    app.include_router(router)
    logger.info("AEGIS-42 routes mounted at /aegis/*")
