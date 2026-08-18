"""Dashboard mining controls — Start/Stop real MiningEngine + mesh workers."""

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
            from dashboard.local_miner import local_status

            fleet = MiningCoordinator(get_comms()).fleet_view()
            local = local_status(get_comms())
            return {"status": "ok", "local": local, **fleet}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/mining/engine/start")
    async def mining_engine_start():
        """
        Start mining to MINING_WALLET.
        1) Local MiningEngine if bfgminer present
        2) Mesh broadcast resume so any workers also mine
        """
        try:
            from dashboard.local_miner import start_local, wallet_configured

            wallet = wallet_configured()
            if not wallet:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "MINING_WALLET not set",
                        "hint": "export MINING_WALLET=bc1q… before compose up",
                    },
                    status_code=400,
                )
            local = start_local(get_comms())
            mesh = {"ok": False}
            try:
                get_comms().broadcast_to_workers({"action": "resume"})
                mesh = {"ok": True, "action": "resume", "target": "all_workers"}
            except Exception as e:
                mesh = {"ok": False, "error": str(e)}

            ok = bool(local.get("ok") or mesh.get("ok"))
            return {
                "ok": ok,
                "wallet": wallet,
                "local": local,
                "mesh": mesh,
                "note": "Pool credits the configured wallet; Aurora does not forge deposits",
            }
        except Exception as e:
            logger.exception("start")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/mining/engine/stop")
    async def mining_engine_stop():
        try:
            from dashboard.local_miner import stop_local

            local = stop_local(get_comms())
            mesh = {"ok": False}
            try:
                get_comms().broadcast_to_workers({"action": "pause"})
                mesh = {"ok": True, "action": "pause", "target": "all_workers"}
            except Exception as e:
                mesh = {"ok": False, "error": str(e)}
            return {"ok": True, "local": local, "mesh": mesh}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/mining/engine/command")
    async def mining_engine_command(
        action: str = Form(...),
        factor: str = Form(""),
        target: str = Form(""),
    ):
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

    logger.info("mining_engine_ops mounted (start/stop)")
