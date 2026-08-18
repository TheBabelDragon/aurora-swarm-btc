"""Dashboard routes: who-holds, repair, epoch, reconstruct."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse, Response

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
        planner = getattr(tm, "repair_planner", None) if tm else None
        if planner is None:
            planner = RepairPlanner(possession, topo)

        def candidates():
            try:
                return [
                    n.get("node_id") or n.get("id")
                    for n in (comms.get_active_nodes() or [])
                    if isinstance(n, dict)
                ]
            except Exception:
                return []

        return RepairExecutor(comms, planner, list_candidates=candidates)

    @app.get("/fabric/who")
    def fabric_who(asset_id: str):
        """Who holds this — claimed vs verified. The anti-spreadsheet endpoint."""
        try:
            from mods.asset_fabric.who import who_holds
            from mods.asset_fabric.possession_verify import PossessionTracker

            tm = _mgr()
            possession = getattr(tm, "possession", None) if tm else PossessionTracker()
            topo = getattr(tm, "topology", None) if tm else None
            policy = getattr(getattr(tm, "repair_planner", None), "policy", None) if tm else None

            claimed_mesh = []
            try:
                from mods.asset_fabric.fabric import AssetFabric

                sp = AssetFabric(get_comms()).swarm_possession(asset_id.strip())
                claimed_mesh = sp.get("holders") or []
            except Exception:
                pass

            result = who_holds(
                asset_id.strip(),
                possession=possession,
                topology=topo,
                policy=policy,
                claimed_from_mesh=claimed_mesh,
            )
            return {"status": "ok", **result}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

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
            return {"status": "ok", **{k: v for k, v in result.items() if k != "epoch"}, "epoch_root": result.get("epoch_root")}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/fabric/epoch/latest")
    def fabric_epoch_latest():
        try:
            raw = get_comms().get_state("epoch:latest")
            return {"status": "ok", "latest": raw}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    @app.post("/fabric/reconstruct")
    async def fabric_reconstruct(asset_id: str = Form(...)):
        """Reconstruct important asset from local RS shards."""
        try:
            from mods.asset_fabric.reconstruct import reconstruct_from_dir

            tm = _mgr()
            if not tm:
                return JSONResponse({"status": "error", "detail": "no torrent manager"}, status_code=400)
            asset_id = asset_id.strip().lower()
            encoding = None
            # Manifest provenance on mesh
            try:
                raw = get_comms().get_state(f"asset:manifest:{asset_id}")
                if isinstance(raw, dict):
                    encoding = (raw.get("provenance") or {}).get("erasure")
            except Exception:
                pass
            if not encoding:
                return JSONResponse(
                    {"status": "error", "detail": "no erasure metadata (not an important asset?)"},
                    status_code=404,
                )
            shard_dir = Path(tm.storage_dir) / "shards"
            result = reconstruct_from_dir(shard_dir, asset_id, encoding)
            if not result.get("ok"):
                return JSONResponse({"status": "error", **result}, status_code=400)
            data = result["data"]
            # Write reconstructed complete file back into torrent storage
            out_name = f"{asset_id}_reconstructed"
            out_path = Path(tm.storage_dir) / out_name
            out_path.write_bytes(data)
            return {
                "status": "ok",
                "asset_id": asset_id,
                "size": len(data),
                "path": str(out_path),
                "present_shards": result.get("present_shards"),
            }
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    logger.info("fabric_ops routes mounted (who/repair/epoch/reconstruct)")
