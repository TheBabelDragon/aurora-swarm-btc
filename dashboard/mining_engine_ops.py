"""Mining routes — respond in milliseconds."""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import Form

logger = logging.getLogger("aurora-dashboard.mining_engine")


def install_mining_engine_ops(app: Any, *, get_comms: Callable[[], Any]):
    @app.get("/mining/engine/status")
    def mining_engine_status():
        try:
            from dashboard.local_miner import local_status

            st = local_status(get_comms()) or {}
            return {
                "ok": True,
                "running": bool(st.get("running")),
                "starting": bool(st.get("starting")),
                "user_stopped": bool(st.get("user_stopped")),
                "backend": st.get("backend") or "cpu_stratum",
                "hashrate_hs": float(st.get("hashrate_hs") or 0),
                "hashrate_display": st.get("hashrate_display") or "idle",
                "wallet": st.get("wallet") or "",
                "pool": st.get("pool") or "",
                "error": st.get("error") or "",
                "engine_built": bool(st.get("engine_built", True)),
            }
        except Exception as e:
            logger.exception("status")
            return {
                "ok": True,
                "running": False,
                "hashrate_display": "idle",
                "error": str(e),
            }

    @app.post("/mining/engine/start")
    async def mining_engine_start():
        try:
            from dashboard.local_miner import start_local

            # Returns immediately; hashing starts in background
            return start_local(get_comms())
        except Exception as e:
            logger.exception("start")
            return {"ok": False, "running": False, "error": str(e), "hashrate_display": "idle"}

    @app.post("/mining/engine/stop")
    async def mining_engine_stop():
        try:
            from dashboard.local_miner import stop_local

            return stop_local(get_comms())
        except Exception as e:
            logger.exception("stop")
            return {"ok": False, "running": False, "error": str(e), "hashrate_display": "idle"}

    @app.post("/mining/engine/command")
    async def mining_engine_command(
        action: str = Form(...),
        target: str = Form(""),
        intensity: str = Form(""),
    ):
        action = (action or "").strip().lower()
        try:
            from dashboard.local_miner import get_local_engine, start_local, stop_local

            comms = get_comms()
            if action == "pause":
                stop_local(comms)
            elif action in ("resume", "restart_miner"):
                if action == "restart_miner":
                    stop_local(comms)
                start_local(comms)
            elif action == "adjust_intensity" and intensity:
                get_local_engine(comms).set_intensity(intensity)
            else:
                return {"ok": False, "error": "unknown action"}
            return {"ok": True, "action": action}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    logger.info("mining_engine_ops mounted (non-blocking)")
