from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from control.bus import Bus
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aurora-dashboard")

app = FastAPI(title="Aurora Swarm BTC — Comms Operations Center")
bus = Bus()

try:
    from dashboard.mining_standalone import install_mining_standalone

    install_mining_standalone(app)
except Exception as e:
    logger.error(f"mining_standalone failed: {e}")


@app.get("/healthz")
def healthz():
    return {"status": "healthy"}


@app.get("/ping")
def ping():
    return {"ok": True}


comms = None
try:
    from comms.layer import CommsLayer
    from comms.node_id import default_node_id

    comms = CommsLayer(node_id=default_node_id("node"))
except Exception as e:
    logger.error(f"CommsLayer init failed: {e}")

    class _Stub:
        node_id = os.getenv("HOSTNAME") or "node"

        def get_active_nodes(self, *a, **k):
            return []

        def get_workers(self, *a, **k):
            return []

        def register_node(self, *a, **k):
            return None

        def heartbeat(self, *a, **k):
            return None

        def set_state(self, *a, **k):
            return None

        def get_state(self, *a, **k):
            return None

        def ping(self):
            return False

    comms = _Stub()

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
        if hasattr(comms, "register_node"):
            comms.register_node(
                node_type="dashboard",
                capabilities=["dashboard", "mesh", "mining_engine", "chat"],
                metadata={"role": "dashboard"},
            )
            comms.heartbeat()
    except Exception:
        pass
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
    mine = {}
    try:
        from dashboard.mining_standalone import _snapshot

        mine = _snapshot()
    except Exception:
        pass
    nodes = []
    try:
        nodes = comms.get_active_nodes() or []
    except Exception:
        pass
    running = bool(mine.get("running"))
    return {
        "status": "healthy",
        "active_workers": len(nodes),
        "hashrate_display": mine.get("hashrate_display") or ("warming up…" if running else "idle"),
        "mining": mine,
        "mood": "Hashing" if running else "Idle",
        "node_id": getattr(comms, "node_id", "?"),
        "fleet_hashrate_display": mine.get("hashrate_display") or "idle",
    }


@app.get("/nodes")
def nodes():
    try:
        return {"nodes": comms.get_active_nodes() or []}
    except Exception as e:
        return {"nodes": [], "error": str(e)}


@app.get("/", response_class=HTMLResponse)
def root():
    p = Path(__file__).resolve().parent / "home_template.html"
    try:
        html = p.read_text(encoding="utf-8")
    except Exception:
        html = "<h1>Aurora</h1><p>home_template.html missing — rebuild image</p>"
    if "/ux/mine.js" not in html:
        html = html.replace("</body>", '<script src="/ux/mine.js"></script>\n</body>')
    return HTMLResponse(content=html)
