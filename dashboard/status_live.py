"""Replace /status with live mining-aware swarm status."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("aurora-dashboard.status_live")


def _aggregate_hashrate_hs(comms: Any, local: dict) -> float:
    total = float(local.get("hashrate_hs") or 0.0)
    if total <= 0 and local.get("hashrate_ghs"):
        total = float(local["hashrate_ghs"]) * 1e9
    try:
        from mods.mining_engine.coordinator import MiningCoordinator

        fleet = MiningCoordinator(comms).fleet_view()
        for w in fleet.get("workers") or []:
            hs = w.get("hashrate_hs")
            if hs is None and w.get("hashrate_ghs") is not None:
                hs = float(w["hashrate_ghs"]) * 1e9
            if hs:
                # avoid double-count local if same worker_id
                if w.get("worker_id") and w.get("worker_id") == local.get("worker_id"):
                    continue
                total += float(hs)
    except Exception:
        pass
    # also scan per-node keys
    try:
        for n in comms.get_active_nodes() or []:
            if not isinstance(n, dict):
                continue
            nid = n.get("node_id") or ""
            st = comms.get_state(f"worker:{nid}:hashrate")
            if isinstance(st, dict):
                hs = st.get("hashrate_hs")
                if hs is None and st.get("hashrate_ghs") is not None:
                    hs = float(st["hashrate_ghs"]) * 1e9
                if hs:
                    total = max(total, float(hs))  # max avoids crude double count
    except Exception:
        pass
    return float(total)


def _format_rate(hs: float) -> str:
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
    return "0 H/s"


def install_status_live(
    app: Any,
    *,
    get_comms: Callable[[], Any],
    bus: Any = None,
):
    try:
        app.router.routes = [
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
            local = {"error": str(e)}

        hs = _aggregate_hashrate_hs(comms, local)
        ghs = hs / 1e9
        ths = hs / 1e12

        # entropy: soft activity score from hashrate + running flag
        entropy = 0.0
        if local.get("running"):
            entropy = 1.5
        if hs > 0:
            # log-ish scale so CPU MH/s still moves the needle
            import math

            entropy = max(entropy, min(5.0, 1.0 + math.log10(max(hs, 1.0)) / 2.0))

        try:
            if bus is not None:
                bus.set("cluster:total_hashrate_btc", ths)
                bus.set("cluster:total_hashrate_hs", hs)
                bus.set("entropy", entropy)
            comms.set_state("cluster:total_hashrate_hs", hs)
            comms.set_state("cluster:total_hashrate_ghs", ghs)
            comms.set_state("entropy", entropy)
        except Exception:
            pass

        workers = []
        try:
            workers = comms.get_workers() or []
        except Exception:
            pass

        return {
            "status": "healthy",
            "entropy": round(entropy, 3),
            "total_ths": round(ths, 6),
            "total_ghs": round(ghs, 6),
            "total_hs": round(hs, 2),
            "hashrate_display": _format_rate(hs),
            "mining": {
                "running": bool(local.get("running")),
                "backend": local.get("backend"),
                "wallet": (local.get("wallet") or "")[:16] + ("…" if local.get("wallet") else ""),
                "hashrate_display": local.get("hashrate_display") or _format_rate(float(local.get("hashrate_hs") or 0)),
            },
            "active_workers": len(workers),
            "current_coin": "BTC",
            "mood": "THEY YEARN FOR THE MINES" if entropy > 2.5 else ("Hashing" if hs > 0 or local.get("running") else "Idle"),
            "message": "Live mining telemetry · Asset Fabric · BVL · attestation",
            "comms_nodes_registered": len(comms.get_active_nodes() or []),
        }

    logger.info("/status live hashrate installed")
