"""Dashboard routes for repair executor and epoch roots."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.fabric")


def mount_fabric_ops(
    app: FastAPI,
    *,
    get_comms: Callable[[], Any],
    get_torrent_manager: Optional[Callable[[], Any]] = None,
):
    def _mgr():
        return get_torrent_manager() if get_torrent_manager else None

    def _executor():
        tm = _mgr()
        if tm and getattr(tm, "repair_executor", None):
            return tm.repair_executor
        from mods.asset_fabric.possession_verify import PossessionTracker
        from mods.asset_fabric.topology import TopologyRegistry, load_topology_from_mesh
        from mods.asset_fabric.repair import RepairPlanner
        from mods.asset_fabric.repair_executor import RepairExecutor

        comms = get_comms()
        possession = getattr(tm, "possession", None) if tm else PossessionTracker()
        topo = getattr(tm, "topology", None) if tm else TopologyRegistry()
        if topo is None:
            topo = TopologyRegistry()
        load_topology_from_mesh(comms, topo)
        planner = getattr(tm, "repair_planner", None) if tm else RepairPlanner(possession, topo)
        if planner is None:
            planner = RepairPlanner(possession, topo)

        def candidates():
            try:
                return [n.get("node_id") or n.get("id") for n in (comms.get_active_nodes() or []) if isinstance(n, dict)]
            except Exception:
                return []

        return RepairExecutor(comms, planner, list_candidates=candidates)

    @app.get("/fabric/availability")
    def fabric_availability(asset_id: str):
        try:
            ex = _executor()
            rep = ex.planner.availability(asset_id.strip())
            return {"status": "ok", **rep.to_dict()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/fabric/repair")
    async def fabric_repair(asset_id: str = Form(...)):
        try:
            return {"status": "ok", **_executor().run_for_asset(asset_id.strip())}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/fabric/epoch")
    async def fabric_epoch(broadcast: str = Form("0")):
        try:
            from mods.asset_fabric.epoch import EpochBuilder

            tm = _mgr()
            b = EpochBuilder(get_comms())
            epoch = b.from_local_state(
                possession=getattr(tm, "possession", None) if tm else None,
                topology_registry=getattr(tm, "topology", None) if tm else None,
                policy=getattr(getattr(tm, "repair_planner", None), "policy", None) if tm else None,
            )
            result = b.commit(epoch, request_broadcast=broadcast in ("1", "true", "yes", "on"))
            return {"status": "ok", **result}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/fabric/epoch/latest")
    def fabric_epoch_latest():
        try:
            raw = get_comms().get_state("epoch:latest")
            return {"status": "ok", "latest": raw}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    logger.info("fabric_ops routes mounted")
