"""Mining Provenance dashboard routes."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.mining")


def mount_mining_ops(app: FastAPI, *, get_comms: Callable[[], Any]):
    def _mp():
        from mods.mining_provenance.service import MiningProvenance

        return MiningProvenance(get_comms())

    @app.get("/mining/who")
    def mining_who(epoch: int):
        try:
            return {"status": "ok", **_mp().who_epoch(int(epoch))}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/mining/worker/{worker_id}")
    def mining_worker(worker_id: str):
        try:
            mp = _mp()
            w = mp.get_worker(worker_id)
            events = [e.to_dict() for e in mp.events_for_worker(worker_id, limit=50)]
            return {
                "status": "ok",
                "worker": w.to_dict() if w else None,
                "events": events,
                "disclaimer": "Aurora observations. Not Bitcoin consensus facts about hardware.",
            }
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/mining/reward/{txid}")
    def mining_reward(txid: str):
        try:
            return {"status": "ok", **_mp().provenance_for_txid(txid.strip())}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/mining/provenance/{txid}")
    def mining_provenance(txid: str):
        return mining_reward(txid)

    @app.get("/mining/utxo/{txid}/{vout}")
    def mining_utxo(txid: str, vout: int):
        try:
            mp = _mp()
            u = mp.get_utxo(txid.strip(), int(vout))
            c = mp.get_custody(f"{txid.strip()}:{int(vout)}")
            return {
                "status": "ok",
                "on_chain": u.to_dict() if u else None,
                "custody_observation": c,
                "bitcoin_proves": "UTXO existence and script/value only.",
                "aurora_observes": "Optional custody path — not an on-chain fact.",
            }
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/mining/observe_share")
    async def mining_observe_share(
        worker_id: str = Form(...),
        epoch: int = Form(...),
        pool_id: str = Form(""),
        job_id: str = Form(""),
        difficulty: float = Form(0.0),
        facility_domain: str = Form("unknown"),
    ):
        try:
            ev = _mp().observe_share(
                worker_id=worker_id.strip(),
                epoch=int(epoch),
                pool_id=pool_id,
                job_id=job_id,
                difficulty=float(difficulty),
                facility_domain=facility_domain,
            )
            return {"status": "ok", "event": ev.to_dict()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/mining/upgrade")
    async def mining_upgrade(
        event_id: str = Form(...),
        level: int = Form(...),
        reward_txid: str = Form(""),
        reward_vout: str = Form(""),
        pool_account: str = Form(""),
    ):
        try:
            from mods.mining_provenance.models import EvidenceLevel

            vout = int(reward_vout) if reward_vout not in ("", None) else None
            ev = _mp().upgrade_evidence(
                event_id.strip(),
                EvidenceLevel(int(level)),
                reward_txid=reward_txid.strip(),
                reward_vout=vout,
                pool_account=pool_account,
            )
            if not ev:
                return JSONResponse({"status": "error", "detail": "event not found"}, status_code=404)
            return {"status": "ok", "event": ev.to_dict()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.post("/mining/register_worker")
    async def mining_register_worker(
        worker_id: str = Form(...),
        node_id: str = Form(""),
        pool_id: str = Form(""),
        facility_domain: str = Form("unknown"),
        hardware_id: str = Form(""),
    ):
        try:
            from mods.mining_provenance.models import WorkerIdentity

            w = _mp().register_worker(
                WorkerIdentity(
                    worker_id=worker_id.strip(),
                    node_id=(node_id or worker_id).strip(),
                    pool_id=pool_id,
                    facility_domain=facility_domain,
                    hardware_id=hardware_id,
                )
            )
            return {"status": "ok", "worker": w.to_dict()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    logger.info("mining_ops routes mounted")
