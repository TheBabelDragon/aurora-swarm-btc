"""Ghostwalk dashboard surfaces — mesh legibility, evidence-backed anomalies.

Read-mostly. Mutation endpoints (ack/resolve finding) require dashboard API key
when AURORA_DASHBOARD_API_KEY is set.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import Query, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.ghostwalk")


def _require_auth(request: Request) -> Optional[JSONResponse]:
    try:
        from dashboard.comms_security import check_dashboard_auth

        ok, detail = check_dashboard_auth(request.headers)
        if ok:
            return None
        return JSONResponse(
            {"ok": False, "error": "unauthorized", "detail": detail or "valid X-API-Key required"},
            status_code=401,
        )
    except Exception:
        return None


def install_ghostwalk_ops(app: Any, *, get_comms: Callable[[], Any]):
    def _gw():
        try:
            from comms.ghostwalk import get_ghostwalk, init_ghostwalk

            svc = get_ghostwalk()
            if svc is not None:
                return svc
            comms = get_comms()
            nid = getattr(comms, "node_id", None) or "dashboard"

            def _node_lookup(n):
                try:
                    for peer in comms.get_active_nodes() or []:
                        if (peer.get("node_id") or "") == n:
                            return peer
                except Exception:
                    pass
                return None

            store = None
            try:
                from mods.evidence_integrity import EvidenceStore

                store = EvidenceStore()
            except Exception:
                pass

            return init_ghostwalk(
                local_node_id=str(nid),
                node_lookup=_node_lookup,
                evidence_store=store,
            )
        except Exception as e:
            logger.debug("ghostwalk unavailable: %s", e)
            return None

    @app.get("/ghostwalk/status")
    def ghostwalk_status():
        svc = _gw()
        if svc is None:
            return {"ok": False, "error": "ghostwalk_unavailable"}
        try:
            # Seed from live mesh peers (observation only)
            try:
                peers = get_comms().get_active_nodes() or []
                for p in peers:
                    nid = (p.get("node_id") or "").strip()
                    if not nid or nid == svc.local_node_id:
                        continue
                    meta = p.get("metadata") or {}
                    caps = p.get("capabilities") or meta.get("capabilities") or []
                    if not isinstance(caps, list):
                        caps = []
                    svc.observe_peer_advertisement(
                        nid,
                        fingerprint=str(meta.get("fingerprint") or p.get("fingerprint") or ""),
                        auth_ok=False,
                        auth_reason="unsigned",
                        capabilities=[str(c) for c in caps][:16],
                    )
            except Exception:
                pass
            return svc.status()
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)

    @app.get("/ghostwalk/topology")
    def ghostwalk_topology():
        svc = _gw()
        if svc is None:
            return {"ok": False, "error": "ghostwalk_unavailable"}
        st = svc.status()
        return {"ok": True, "topology": st.get("topology"), "peer_counts": st.get("peer_counts")}

    @app.get("/ghostwalk/findings")
    def ghostwalk_findings(open_only: bool = Query(True)):
        svc = _gw()
        if svc is None:
            return {"ok": False, "error": "ghostwalk_unavailable", "findings": []}
        return {"ok": True, "findings": svc.anomalies.list_findings(open_only=open_only)}

    @app.get("/ghostwalk/proposals")
    def ghostwalk_proposals():
        svc = _gw()
        if svc is None:
            return {"ok": False, "error": "ghostwalk_unavailable", "proposals": []}
        return {"ok": True, "proposals": svc.recovery.list_proposals(active_only=True)}

    @app.get("/ghostwalk/evidence")
    def ghostwalk_evidence(limit: int = Query(30, ge=1, le=100)):
        svc = _gw()
        if svc is None:
            return {"ok": False, "error": "ghostwalk_unavailable", "items": []}
        return {"ok": True, "items": svc.evidence.recent(limit)}

    @app.get("/ghostwalk/timeline")
    def ghostwalk_timeline(limit: int = Query(40, ge=1, le=100)):
        svc = _gw()
        if svc is None:
            return {"ok": False, "error": "ghostwalk_unavailable", "timeline": []}
        return {"ok": True, "timeline": svc.topology.timeline(limit)}

    @app.post("/ghostwalk/findings/{finding_id}/ack")
    async def ghostwalk_ack_finding(finding_id: str, request: Request):
        denied = _require_auth(request)
        if denied is not None:
            return denied
        svc = _gw()
        if svc is None:
            return JSONResponse({"ok": False, "error": "ghostwalk_unavailable"}, status_code=503)
        f = svc.anomalies.acknowledge(finding_id)
        if not f:
            return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
        return {"ok": True, "finding": f.to_dict()}

    @app.post("/ghostwalk/findings/{finding_id}/resolve")
    async def ghostwalk_resolve_finding(finding_id: str, request: Request):
        denied = _require_auth(request)
        if denied is not None:
            return denied
        svc = _gw()
        if svc is None:
            return JSONResponse({"ok": False, "error": "ghostwalk_unavailable"}, status_code=503)
        reason = ""
        try:
            body = await request.json()
            reason = str(body.get("reason") or "")
        except Exception:
            pass
        f = svc.anomalies.resolve(finding_id, reason=reason)
        if not f:
            return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
        return {"ok": True, "finding": f.to_dict()}

    logger.info("ghostwalk_ops mounted")
