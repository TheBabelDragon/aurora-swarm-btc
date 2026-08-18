"""Dashboard routes for MiningEngine fleet control — real status only."""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.mining_engine")


def install_mining_engine_ops(app: Any, *, get_comms: Callable[[], Any]):
    @app.get("/mining/engine/status")
    def mining_engine_status():
        try:
            from mods.mining_engine.coordinator import MiningCoordinator

            fleet = MiningCoordinator(get_comms()).fleet_view()
            return {"status": "ok", **fleet}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/mining/engine/command")
    async def mining_engine_command(
        action: str = Form(...),
        factor: str = Form(""),
        target: str = Form(""),
    ):
        """Broadcast or target mesh mining commands (pause/resume/intensity/restart)."""
        action = (action or "").strip()
        if action not in ("pause", "resume", "restart_miner", "adjust_intensity"):
            return JSONResponse({"ok": False, "error": "unsupported action"}, status_code=400)
        payload = {"action": action}
        if action == "adjust_intensity":
            if not factor:
                return JSONResponse({"ok": False, "error": "factor required"}, status_code=400)
            payload["factor"] = factor
        try:
            comms = get_comms()
            if target.strip():
                comms.send_to_node(target.strip(), payload)
            else:
                comms.broadcast_to_workers(payload)
            return {"ok": True, "action": action, "target": target.strip() or "all_workers"}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    logger.info("mining_engine_ops mounted")
