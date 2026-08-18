"""/status — local mining truth first; fleet rate is separate."""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

logger = logging.getLogger("aurora-dashboard.status_live")


def _format_rate(hs: float, *, running: bool = False, starting: bool = False) -> str:
    if starting and hs <= 0:
        return "warming up…"
    if not running:
        return "idle"
    if hs >= 1e12:
        return f"{hs/1e12:.3f} TH/s"
    if hs >= 1e9:
        return f"{hs/1e9:.3f} GH/s"
    if hs >= 1e6:
        return f"{hs/1e6:.2f} MH/s"
    if hs >= 1e3:
        return f"{hs/1e3:.2f} KH/s"
    if hs > 0:
        return f"{hs:.0f} H/s"
    return "warming up…"


def _fleet_hashrate_hs(comms: Any, local_hs: float) -> float:
    total = float(local_hs or 0)
    seen = {getattr(comms, "node_id", "")}
    try:
        for n in comms.get_active_nodes() or []:
            nid = n.get("node_id") or ""
            if not nid or nid in seen:
                continue
            meta = n.get("metadata") or {}
            hs = meta.get("hashrate_hs")
            if hs is None:
                st = comms.get_state(f"worker:{nid}:hashrate")
                if isinstance(st, dict) and st.get("running"):
                    hs = st.get("hashrate_hs") or 0
            if hs:
                total += float(hs)
                seen.add(nid)
    except Exception:
        pass
    return float(total)


def install_status_live(app: Any, *, get_comms, bus: Optional[Any] = None):
    try:
        app.router.routes[:] = [
            r
            for r in app.router.routes
            if not (
                getattr(r, "path", None) == "/status"
                and "GET" in (getattr(r, "methods", set()) or set())
            )
        ]
    except Exception as e:
        logger.warning(f"prune /status: {e}")

    @app.get("/status")
    def status_live():
        comms = get_comms()
        local = {}
        try:
            from dashboard.local_miner import local_status

            local = local_status(comms) or {}
        except Exception as e:
            local = {"running": False, "hashrate_hs": 0, "error": str(e)}

        running = bool(local.get("running"))
        user_stopped = bool(local.get("user_stopped"))
        hs_local = float(local.get("hashrate_hs") or 0) if running else 0.0
        starting = running and hs_local <= 0
        local_display = _format_rate(hs_local, running=running, starting=starting)

        fleet_hs = _fleet_hashrate_hs(comms, hs_local)
        fleet_display = _format_rate(fleet_hs, running=fleet_hs > 0 or running, starting=False)

        entropy = 0.1
        if running:
            entropy = 1.5
        if hs_local > 0:
            entropy = max(entropy, min(5.0, 1.0 + math.log10(max(hs_local, 1.0)) / 2.0))

        try:
            nid = comms.node_id
            comms.set_state(
                f"worker:{nid}:hashrate",
                {
                    "hashrate_hs": hs_local,
                    "hashrate_display": local_display,
                    "running": running,
                },
                expire=120,
            )
        except Exception:
            pass

        workers = []
        try:
            workers = comms.get_workers() or []
        except Exception:
            pass

        mood = "Idle"
        if user_stopped:
            mood = "Stopped by user"
        elif starting:
            mood = "Warming up"
        elif running:
            mood = "Hashing"

        # hashrate_display = THIS NODE only so Status never fights Mining panel
        return {
            "status": "healthy",
            "entropy": round(entropy, 3),
            "total_hs": round(hs_local, 2),
            "hashrate_display": local_display,
            "fleet_hashrate_hs": fleet_hs,
            "fleet_hashrate_display": fleet_display,
            "mining": {
                "running": running,
                "user_stopped": user_stopped,
                "starting": starting,
                "engine_built": bool(local.get("engine_built", True)),
                "backend": local.get("backend") or "cpu_stratum",
                "wallet": (local.get("wallet") or "")[:20],
                "pool": local.get("pool") or "",
                "hashrate_hs": hs_local,
                "hashrate_display": local_display,
                "error": local.get("error") or "",
            },
            "active_workers": len(workers),
            "current_coin": "BTC",
            "mood": mood,
            "message": "Local mining status is authoritative on this page",
            "comms_nodes_registered": len(comms.get_active_nodes() or []),
        }

    logger.info("/status local-truth installed")
