"""Replace /status with live mining-aware swarm status — no fake 0 H/s."""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

logger = logging.getLogger("aurora-dashboard.status_live")


def _format_rate(hs: float, *, running: bool = False, starting: bool = False) -> str:
    if starting and hs <= 0:
        return "warming up…"
    if not running and hs <= 0:
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
    return "measuring…" if running else "idle"


def _aggregate_hashrate_hs(comms: Any, local: dict) -> float:
    total = float(local.get("hashrate_hs") or 0.0)
    if total <= 0 and local.get("hashrate_ghs"):
        total = float(local["hashrate_ghs"]) * 1e9
    seen = {comms.node_id}
    try:
        for w in comms.get_workers() or []:
            nid = w.get("node_id") or w.get("id")
            hs = w.get("hashrate_hs")
            if hs is None and w.get("hashrate_ghs") is not None:
                hs = float(w["hashrate_ghs"]) * 1e9
            if hs and nid not in seen:
                total += float(hs)
                seen.add(nid)
    except Exception:
        pass
    try:
        for n in comms.get_active_nodes() or []:
            nid = n.get("node_id") or ""
            if nid in seen:
                continue
            meta = n.get("metadata") or {}
            hs = meta.get("hashrate_hs")
            if hs is None:
                st = comms.get_state(f"worker:{nid}:hashrate")
                if isinstance(st, dict):
                    hs = st.get("hashrate_hs")
                    if hs is None and st.get("hashrate_ghs") is not None:
                        hs = float(st["hashrate_ghs"]) * 1e9
            if hs:
                total += float(hs)
                seen.add(nid)
    except Exception:
        pass
    return float(total)


def install_status_live(app: Any, *, get_comms, bus: Optional[Any] = None):
    # prune prior /status if present
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
            local = {"error": str(e), "running": False}

        running = bool(local.get("running"))
        engine_built = bool(local.get("engine_built") or local.get("backend"))
        hs_local = float(local.get("hashrate_hs") or 0)
        starting = running and hs_local <= 0

        hs = _aggregate_hashrate_hs(comms, local)
        ghs = hs / 1e9
        ths = hs / 1e12

        entropy = 0.0
        if running:
            entropy = 1.5
        if hs > 0:
            entropy = max(entropy, min(5.0, 1.0 + math.log10(max(hs, 1.0)) / 2.0))

        try:
            if bus is not None:
                bus.set("cluster:total_hashrate_btc", ths)
                bus.set("cluster:total_hashrate_hs", hs)
                bus.set("entropy", entropy)
            # publish local rate for mesh aggregation
            if running or hs_local > 0:
                comms.set_state(
                    f"worker:{comms.node_id}:hashrate",
                    {
                        "hashrate_hs": hs_local,
                        "hashrate_display": _format_rate(hs_local, running=running, starting=starting),
                        "running": running,
                    },
                    expire=120,
                )
            comms.set_state("cluster:total_hashrate_hs", hs)
            comms.set_state("entropy", entropy)
        except Exception:
            pass

        workers = []
        try:
            workers = comms.get_workers() or []
        except Exception:
            pass

        display = _format_rate(hs, running=running or hs > 0, starting=starting and hs <= 0)
        local_display = _format_rate(hs_local, running=running, starting=starting)

        mood = "Idle"
        if starting:
            mood = "Warming up"
        elif hs > 0 or running:
            mood = "THEY YEARN FOR THE MINES" if entropy > 2.5 else "Hashing"

        return {
            "status": "healthy",
            "entropy": round(entropy, 3),
            "total_ths": round(ths, 6),
            "total_ghs": round(ghs, 6),
            "total_hs": round(hs, 2),
            "hashrate_display": display,
            "mining": {
                "running": running,
                "starting": starting,
                "engine_built": engine_built,
                "backend": local.get("backend") or "cpu_stratum",
                "wallet": (local.get("wallet") or "")[:16] + ("…" if local.get("wallet") else ""),
                "hashrate_hs": hs_local,
                "hashrate_display": local_display,
                "error": local.get("error") or "",
            },
            "active_workers": len(workers),
            "current_coin": "BTC",
            "mood": mood,
            "message": "Live mining telemetry · shared mesh chat · BVL",
            "comms_nodes_registered": len(comms.get_active_nodes() or []),
        }

    logger.info("/status live hashrate installed")
