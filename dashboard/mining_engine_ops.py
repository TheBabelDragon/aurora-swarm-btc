"""Dashboard mining controls — always respond; single engine path."""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.mining_engine")


def install_mining_engine_ops(app: Any, *, get_comms: Callable[[], Any]):
    @app.get("/mining/engine/status")
    def mining_engine_status():
        # ALWAYS 200 JSON so the UI never shows "unreachable"
        try:
            from dashboard.local_miner import local_status

            st = local_status(get_comms()) or {}
            running = bool(st.get("running"))
            return {
                "ok": True,
                "running": running,
                "user_stopped": bool(st.get("user_stopped")),
                "backend": st.get("backend") or "cpu_stratum",
                "hashrate_hs": float(st.get("hashrate_hs") or 0),
                "hashrate_display": st.get("hashrate_display")
                or ("warming up…" if running else "idle"),
                "wallet": st.get("wallet") or "",
                "pool": st.get("pool") or "",
                "error": st.get("error") or "",
                "engine_built": True,
            }
        except Exception as e:
            logger.exception("status")
            return {
                "ok": True,
                "running": False,
                "hashrate_hs": 0,
                "hashrate_display": "idle",
                "error": str(e),
                "engine_built": False,
            }

    @app.post("/mining/engine/start")
    async def mining_engine_start():
        try:
            from dashboard.local_miner import local_status, start_local

            comms = get_comms()
            cur = local_status(comms)
            if cur.get("running"):
                return {
                    "ok": True,
                    "already": True,
                    "running": True,
                    "hashrate_display": cur.get("hashrate_display") or "warming up…",
                    "backend": cur.get("backend"),
                    "error": cur.get("error") or "",
                }
            local = start_local(comms)
            return {
                "ok": bool(local.get("ok")),
                "running": bool(local.get("running")),
                "hashrate_display": local.get("hashrate_display") or "warming up…",
                "backend": local.get("backend"),
                "wallet": local.get("wallet"),
                "pool": local.get("pool"),
                "error": local.get("error") or "",
            }
        except Exception as e:
            logger.exception("start")
            return {
                "ok": False,
                "running": False,
                "error": str(e),
                "hashrate_display": "idle",
            }

    @app.post("/mining/engine/stop")
    async def mining_engine_stop():
        try:
            from dashboard.local_miner import stop_local

            stop_local(get_comms())
            return {
                "ok": True,
                "running": False,
                "hashrate_display": "idle",
                "user_stopped": True,
            }
        except Exception as e:
            logger.exception("stop")
            return {
                "ok": False,
                "running": False,
                "hashrate_display": "idle",
                "error": str(e),
            }

    @app.post("/mining/engine/command")
    async def mining_engine_command(
        action: str = Form(...),
        target: str = Form(""),
        intensity: str = Form(""),
    ):
        action = (action or "").strip().lower()
        if action not in ("pause", "resume", "restart_miner", "adjust_intensity"):
            return {"ok": False, "error": "unknown action"}
        try:
            from dashboard.local_miner import get_local_engine, start_local, stop_local

            comms = get_comms()
            if action == "pause":
                stop_local(comms)
            elif action == "resume":
                start_local(comms)
            elif action == "restart_miner":
                stop_local(comms)
                start_local(comms)
            elif action == "adjust_intensity" and intensity:
                get_local_engine(comms).set_intensity(intensity)
            return {"ok": True, "action": action}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    logger.info("mining_engine_ops mounted (always-respond status)")
