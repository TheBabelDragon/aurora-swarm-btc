from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from control.bus import Bus
from comms.layer import CommsLayer, SwarmMessage
import uvicorn
import logging
import time
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aurora-dashboard")

app = FastAPI(title="Aurora Swarm BTC — Comms Operations Center")
bus = Bus()
from comms.node_id import default_node_id
comms = CommsLayer(node_id=default_node_id("node"))
try:
    comms.register_node(
        node_type="dashboard",
        capabilities=["dashboard", "mesh", "mining_engine", "chat"],
        metadata={"role": "dashboard"},
    )
    comms.heartbeat()
except Exception:
    pass

_torrent_manager = None
_anchor_service = None
_identity_service = None
_fabric = None


def get_torrent_manager():
    global _torrent_manager
    if _torrent_manager is None:
        try:
            from mods.torrent_protocol.manager import TorrentManager

            _torrent_manager = TorrentManager(comms)
            _torrent_manager.start_background()
        except Exception as e:
            logger.warning(f"TorrentManager unavailable: {e}")
    return _torrent_manager


def get_anchor():
    global _anchor_service
    if _anchor_service is None:
        try:
            from mods.btc_anchor.service import AnchorService

            _anchor_service = AnchorService(comms)
        except Exception as e:
            logger.warning(f"btc_anchor unavailable: {e}")
    return _anchor_service


def get_identity():
    global _identity_service
    if _identity_service is None:
        try:
            from mods.btc_identity.service import IdentityService

            _identity_service = IdentityService(comms)
        except Exception as e:
            logger.warning(f"btc_identity unavailable: {e}")
    return _identity_service


def get_fabric():
    global _fabric
    if _fabric is None:
        try:
            from mods.asset_fabric.fabric import AssetFabric

            _fabric = AssetFabric(comms)
        except Exception as e:
            logger.warning(f"asset_fabric unavailable: {e}")
    return _fabric


@app.on_event("startup")
async def startup():
    try:
        from dashboard.boot_ops import boot

        boot(
            app,
            get_comms=lambda: comms,
            get_torrent_manager=get_torrent_manager,
            get_anchor=get_anchor,
            get_identity=get_identity,
            get_fabric=get_fabric,
            bus=bus,
        )
    except Exception as e:
        logger.warning(f"startup boot: {e}")


@app.get("/status")
def status():
    entropy = float(bus.get("cluster:entropy") or 0.0)
    total_ths = float(bus.get("cluster:total_hashrate_btc") or 0.0)
    nodes = comms.get_active_nodes()
    return {
        "active_workers": len(nodes),
        "entropy": round(entropy, 4),
        "total_ths": round(total_ths, 3),
        "mood": "stable" if entropy < 0.35 else "elevated",
        "node_id": comms.node_id,
    }


@app.get("/nodes")
def nodes():
    return {"nodes": comms.get_active_nodes()}


@app.get("/events")
def events(limit: int = 20):
    return {"events": comms.get_recent_events(limit)}


@app.get("/comms-health")
def comms_health():
    return {"ok": True, "node_id": comms.node_id, "redis": getattr(comms, "redis_url", "")}


@app.post("/command/broadcast")
async def command_broadcast(action: str = Form(...), factor: Optional[float] = Form(None), reason: str = Form("dash")):
    body = {"action": action, "reason": reason}
    if factor is not None:
        body["factor"] = factor
    try:
        comms.broadcast_to_workers(body)
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)
    return {"status": "ok", "action": action}


@app.post("/command/to_node/{node_id}")
async def command_to_node(node_id: str, action: str = Form(...), reason: str = Form("dash")):
    try:
        comms.send_to_node(node_id, {"action": action, "reason": reason})
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)
    return {"status": "ok", "target": node_id, "action": action}


@app.get("/torrent/status")
def torrent_status():
    tm = get_torrent_manager()
    if not tm:
        return {"torrent_capable_nodes": 0, "downloading": [], "seeding": []}
    return tm.status()


@app.post("/torrent/upload")
async def torrent_upload(file: UploadFile = File(...)):
    tm = get_torrent_manager()
    if not tm:
        return JSONResponse({"status": "error", "detail": "No TorrentManager"}, status_code=400)
    data = await file.read()
    meta = tm.seed_bytes(data, name=file.filename or "upload.bin")
    return {"status": "ok", "infohash": meta.infohash, "name": meta.name}


@app.post("/torrent/ensure")
async def torrent_ensure(infohash: str = Form(...)):
    tm = get_torrent_manager()
    if not tm:
        return JSONResponse({"status": "error", "detail": "No TorrentManager"}, status_code=400)
    tm.ensure(infohash.strip().lower())
    return {"status": "ok"}


@app.post("/torrent/cancel")
async def torrent_cancel(infohash: str = Form(...)):
    tm = get_torrent_manager()
    if not tm:
        return JSONResponse({"status": "error", "detail": "No TorrentManager"}, status_code=400)
    tm.cancel(infohash.strip().lower())
    return {"status": "ok"}


@app.post("/torrent/announce")
async def torrent_announce(infohash: str = Form(...)):
    tm = get_torrent_manager()
    if not tm:
        return JSONResponse({"status": "error", "detail": "No TorrentManager"}, status_code=400)
    tm.announce(infohash.strip().lower())
    return {"status": "ok"}


@app.post("/torrent/broadcast")
async def torrent_broadcast(infohash: str = Form(...)):
    anc = get_anchor()
    if not anc:
        return JSONResponse({"status": "error", "detail": "btc_anchor not available"}, status_code=400)
    anc.queue.enqueue(infohash.strip().lower())
    return {"status": "ok"}


@app.post("/torrent/process_broadcasts")
async def torrent_process_broadcasts():
    anc = get_anchor()
    if not anc:
        return JSONResponse({"status": "error", "detail": "btc_anchor not available"}, status_code=400)
    n = anc.process_queue()
    return {"status": "ok", "processed": n}


@app.post("/torrent/process_broadcasts_batched")
async def torrent_process_batched():
    anc = get_anchor()
    if not anc:
        return JSONResponse({"status": "error", "detail": "btc_anchor not available"}, status_code=400)
    return anc.process_queue_batched()


@app.post("/torrent/anchor")
async def torrent_anchor(infohash: str = Form(...)):
    anc = get_anchor()
    if not anc:
        return JSONResponse({"status": "error", "detail": "btc_anchor not available"}, status_code=400)
    return anc.attest(infohash.strip().lower())


@app.get("/torrent/broadcast_queue")
def torrent_broadcast_queue():
    anc = get_anchor()
    if not anc:
        return {"items": [], "error": "btc_anchor not available"}
    return {"items": anc.queue.list_all(40), "pending": len(anc.queue.list_pending())}


@app.get("/torrent/file/{infohash}")
def torrent_file(infohash: str):
    tm = get_torrent_manager()
    if not tm:
        return JSONResponse({"status": "error", "detail": "No local TorrentManager"}, status_code=400)
    infohash = infohash.strip().lower()
    path = tm.get_path(infohash)
    if not path or not path.exists():
        return JSONResponse({"status": "error", "detail": "File not found or not complete"}, status_code=404)
    meta = tm.torrents.get(infohash)
    return FileResponse(path, filename=(meta.name if meta else path.name), media_type="application/octet-stream")


@app.get("/healthz")
def healthz():
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse)
def root():
    p = Path(__file__).resolve().parent / "home_template.html"
    try:
        html = p.read_text(encoding="utf-8")
    except Exception:
        html = "<h1>Aurora</h1><p>home_template.html missing — rebuild image</p>"
    return HTMLResponse(content=html)


try:
    from dashboard.boot_ops import boot

    boot(
        app,
        get_comms=lambda: comms,
        get_torrent_manager=get_torrent_manager,
        get_anchor=get_anchor,
        get_identity=get_identity,
        get_fabric=get_fabric,
        bus=bus,
    )
except Exception as e:
    logger.warning(f"boot at import: {e}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
