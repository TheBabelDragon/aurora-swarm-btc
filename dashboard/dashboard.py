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
comms = CommsLayer(node_id="dashboard")

_torrent_manager = None
_anchor_service = None
_fabric = None
_identity = None
UPLOAD_DIR = Path(os.getenv("AURORA_UPLOAD_DIR", "/tmp/aurora_uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def get_torrent_manager():
    global _torrent_manager
    if _torrent_manager is None:
        try:
            from mods.torrent_protocol.torrent_manager import TorrentManager, register_torrent_capability
            register_torrent_capability(comms, extra_caps=["dashboard", "torrent"])
            _torrent_manager = TorrentManager(comms, auto_maintain=True)
            logger.info("Dashboard TorrentManager online")
        except Exception as e:
            logger.warning(f"TorrentManager not available on dashboard: {e}")
            _torrent_manager = False
    return _torrent_manager if _torrent_manager is not False else None

def get_anchor():
    global _anchor_service
    if _anchor_service is None:
        try:
            from mods.btc_anchor.anchor import AssetAnchor
            _anchor_service = AssetAnchor(comms)
            logger.info("Dashboard AssetAnchor online")
        except Exception as e:
            logger.debug(f"btc_anchor not available: {e}")
            _anchor_service = False
    return _anchor_service if _anchor_service is not False else None

def get_identity():
    global _identity
    if _identity is None:
        try:
            from mods.btc_identity.identity import NodeIdentity
            _identity = NodeIdentity(comms)
            logger.info("Dashboard NodeIdentity online")
        except Exception as e:
            logger.debug(f"btc_identity not available: {e}")
            _identity = False
    return _identity if _identity is not False else None

def get_fabric():
    global _fabric
    if _fabric is None:
        try:
            from mods.asset_fabric.fabric import AssetFabric
            _fabric = AssetFabric(comms)
            logger.info("Dashboard AssetFabric online")
        except Exception as e:
            logger.debug(f"asset_fabric not available: {e}")
            _fabric = False
    return _fabric if _fabric is not False else None


@app.get("/status")
def status():
    entropy = float(bus.get("entropy") or 0.0)
    total_ths = float(bus.get("cluster:total_hashrate_btc") or 0.0)
    workers = comms.get_workers()
    return {
        "status": "healthy",
        "entropy": round(entropy, 3),
        "total_ths": round(total_ths, 3),
        "active_workers": len(workers) if workers else bus.get("worker_count", 0),
        "current_coin": bus.get("cluster:current_coin", "BTC"),
        "mood": "THEY YEARN FOR THE MINES" if entropy > 2.5 else "Patiently Hashing",
        "message": "They do yearn. Mesh + Asset Fabric + Bitcoin attestation.",
        "comms_nodes_registered": len(comms.get_active_nodes())
    }

@app.get("/nodes")
def get_nodes():
    return {"nodes": comms.get_active_nodes()}

@app.get("/events")
def get_events(limit: int = 20):
    return {"events": comms.get_recent_events(limit)}

@app.get("/comms-health")
def comms_health():
    return {
        "comms_layer": "operational",
        "node_id": comms.node_id,
        "active_nodes": len(comms.get_active_nodes()),
        "recent_events_count": len(comms.get_recent_events(5))
    }

@app.post("/command/broadcast")
async def broadcast_command(action: str = Form(...), factor: float = Form(None), reason: str = Form("manual")):
    payload = {"action": action}
    if factor is not None:
        payload["factor"] = factor
    if reason:
        payload["reason"] = reason
    comms.broadcast_to_workers(payload)
    return {"status": "sent", "action": action, "target": "all_workers"}

@app.post("/command/to_node/{node_id}")
async def command_to_node(node_id: str, action: str = Form(...), factor: float = Form(None), reason: str = Form("manual")):
    payload = {"action": action}
    if factor is not None:
        payload["factor"] = factor
    if reason:
        payload["reason"] = reason
    comms.send_to_node(node_id, payload)
    return {"status": "sent", "action": action, "target": node_id}

def _anchor_view(asset_id: str):
    anc = get_anchor()
    if not anc:
        return None
    try:
        rec = anc.get(asset_id)
        if not rec:
            return None
        return {"status": rec.status, "commitment": rec.commitment, "txid": rec.txid, "method": rec.method, "created_at": rec.created_at}
    except Exception:
        return None

@app.get("/torrent/status")
def torrent_status():
    tm = get_torrent_manager()
    fabric = get_fabric()
    torrent_nodes = comms.get_nodes_by_capability("torrent") if hasattr(comms, "get_nodes_by_capability") else []
    if fabric:
        try:
            fabric.publish_possession_snapshot()
        except Exception:
            pass
    local = []
    if tm:
        local = tm.list_torrents()
        for t in local:
            meta = tm.torrents.get(t.get("infohash"))
            if meta:
                t["size"] = meta.size
                t["name"] = t.get("name") or meta.name
            ih = t.get("infohash")
            if ih:
                t["anchor"] = _anchor_view(ih)
                if fabric:
                    try:
                        sp = fabric.swarm_possession(ih)
                        t["holder_count"] = sp.get("holder_count", 0)
                        t["holders"] = sp.get("holders", [])
                    except Exception:
                        t["holder_count"] = 1 if t.get("complete") else 0
    announced = []
    try:
        keys = comms.r.keys("aurora:torrent:*") if hasattr(comms, "r") else []
        for k in keys[:60]:
            key = k.replace("aurora:", "", 1) if k.startswith("aurora:") else k
            raw = comms.get_state(key)
            if isinstance(raw, dict) and "infohash" in raw:
                announced.append({
                    "infohash": raw.get("infohash"), "name": raw.get("name"), "size": raw.get("size"),
                    "num_pieces": raw.get("num_pieces") or len(raw.get("piece_hashes", [])),
                    "created_by": raw.get("created_by"),
                })
    except Exception as e:
        logger.debug(f"scan announced: {e}")
    downloading = [t for t in local if not t.get("complete")]
    seeding = [t for t in local if t.get("complete")]
    return {
        "torrent_capable_nodes": len(torrent_nodes), "local_torrents": local,
        "downloading": downloading, "seeding": seeding, "announced_torrents": announced,
        "dashboard_has_manager": tm is not None, "dashboard_has_anchor": get_anchor() is not None,
        "dashboard_has_fabric": fabric is not None,
    }

@app.post("/torrent/upload")
async def torrent_upload(file: UploadFile = File(...), name: str = Form(None), anchor: str = Form(None)):
    tm = get_torrent_manager()
    if not tm:
        return JSONResponse({"status": "error", "detail": "No local TorrentManager"}, status_code=400)
    if not file.filename:
        return JSONResponse({"status": "error", "detail": "No filename"}, status_code=400)
    dest = UPLOAD_DIR / f"{int(time.time())}_{Path(file.filename).name}"
    try:
        content = await file.read()
        if not content:
            return JSONResponse({"status": "error", "detail": "Empty file"}, status_code=400)
        dest.write_bytes(content)
        meta = tm.create_torrent(dest, name=name or file.filename)
        tm.announce(meta.infohash)
        anchored = False
        if anchor in ("1", "true", "yes", "on"):
            anc = get_anchor()
            if anc:
                try:
                    from mods.asset_fabric.manifest_model import AssetManifest
                    anc.anchor_manifest(AssetManifest.from_torrent_meta(meta))
                    anchored = True
                except Exception as e:
                    logger.warning(f"Anchor on upload failed: {e}")
        if get_fabric():
            try:
                get_fabric().publish_possession_snapshot()
            except Exception:
                pass
        return {"status": "ok", "infohash": meta.infohash, "name": meta.name, "size": meta.size, "num_pieces": len(meta.piece_hashes), "anchored": anchored}
    except Exception as e:
        logger.exception("upload failed")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

@app.post("/torrent/ensure")
async def torrent_ensure(infohash: str = Form(...), name: str = Form(None)):
    infohash = infohash.strip().lower()
    try:
        msg = SwarmMessage(type="asset.needed", payload={"infohash": infohash, "name": name or "", "source": "dashboard"}, source=comms.node_id)
        comms.publish_message("asset.needed", msg)
    except Exception as e:
        logger.warning(str(e))
    tm = get_torrent_manager()
    local = tm.ensure_asset(infohash=infohash, name=name) if tm else None
    return {"status": "ok", "infohash": infohash, "published_to_mesh": True, "local_manager": local is not None}

@app.post("/torrent/announce")
async def torrent_announce(infohash: str = Form(...)):
    tm = get_torrent_manager()
    if not tm:
        return JSONResponse({"status": "error", "detail": "No local TorrentManager"}, status_code=400)
    ok = tm.announce(infohash.strip().lower())
    return {"status": "ok" if ok else "failed", "infohash": infohash}

@app.post("/torrent/cancel")
async def torrent_cancel(infohash: str = Form(...)):
    tm = get_torrent_manager()
    if not tm:
        return JSONResponse({"status": "error", "detail": "No local TorrentManager"}, status_code=400)
    infohash = infohash.strip().lower()
    tm.wanted.discard(infohash)
    tm.pending.pop(infohash, None)
    return {"status": "ok", "infohash": infohash}

@app.post("/torrent/anchor")
async def torrent_anchor(infohash: str = Form(...)):
    anc = get_anchor()
    tm = get_torrent_manager()
    if not anc or not tm:
        return JSONResponse({"status": "error", "detail": "anchor/manager unavailable"}, status_code=400)
    infohash = infohash.strip().lower()
    meta = tm.torrents.get(infohash)
    if not meta:
        return JSONResponse({"status": "error", "detail": "Unknown asset"}, status_code=404)
    from mods.asset_fabric.manifest_model import AssetManifest
    rec = anc.anchor_manifest(AssetManifest.from_torrent_meta(meta))
    if not rec:
        return JSONResponse({"status": "error", "detail": "anchor failed"}, status_code=500)
    return {"status": "ok", "infohash": infohash, "commitment": rec.commitment, "anchor_status": rec.status}

@app.post("/torrent/broadcast")
async def torrent_broadcast(infohash: str = Form(...)):
    anc = get_anchor()
    if not anc:
        return JSONResponse({"status": "error", "detail": "btc_anchor not available"}, status_code=400)
    infohash = infohash.strip().lower()
    rec = anc.get(infohash)
    if not rec:
        tm = get_torrent_manager()
        if tm and infohash in tm.torrents:
            from mods.asset_fabric.manifest_model import AssetManifest
            rec = anc.anchor_manifest(AssetManifest.from_torrent_meta(tm.torrents[infohash]), request_broadcast=True)
            if rec:
                return {"status": "ok", "infohash": infohash, "queued": True, "commitment": rec.commitment}
        return JSONResponse({"status": "error", "detail": "No anchor record; Anchor first"}, status_code=404)
    ok = anc.request_broadcast(infohash)
    return {"status": "ok" if ok else "error", "infohash": infohash, "queued": ok}

@app.post("/torrent/process_broadcasts")
async def torrent_process_broadcasts():
    anc = get_anchor()
    if not anc:
        return JSONResponse({"status": "error", "detail": "btc_anchor not available"}, status_code=400)
    results = anc.process_queue(max_items=10)
    return {"status": "ok", "processed": len(results), "results": results}

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
    html = """<!DOCTYPE html><html><head><title>Aurora Swarm — Comms Operations Center</title>
<style>
body{font-family:system-ui,sans-serif;background:#0a0a0a;color:#0f0;margin:40px}
h1,h2{color:#0f0;margin-top:0}h3{color:#0c0;margin-bottom:8px}
.card{background:#111;border:1px solid #0f0;padding:20px;margin:20px 0;border-radius:8px}
pre{background:#000;padding:15px;overflow-x:auto;font-size:.85em}.metric{font-size:2em;font-weight:bold}
button{background:#003300;color:#0f0;border:1px solid #0f0;padding:7px 14px;margin:3px;cursor:pointer;border-radius:4px}
button.small{padding:4px 10px;font-size:.8em}button.danger{background:#300;border-color:#f66;color:#f66}
input{background:#000;color:#0f0;border:1px solid #0f0;padding:6px;margin:4px;border-radius:4px;width:240px}
.success{color:#0f0}.error{color:#f66}.muted{color:#6a6;font-size:.85em}
.badge{display:inline-block;background:#003300;border:1px solid #0f0;padding:2px 8px;border-radius:10px;font-size:.75em;margin-left:4px}
.badge.ok{background:#030}.badge.warn{background:#330;border-color:#aa0;color:#ff0}
.badge.anchor{background:#012;border-color:#0af;color:#0af}.section{margin-top:18px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px 6px;border-bottom:1px solid #1a1a1a}
.mono{font-family:ui-monospace,monospace;font-size:.85em}
.progress-bar{background:#222;border:1px solid #0f0;height:14px;border-radius:4px;overflow:hidden}
.progress-fill{background:#0a0;height:100%}
</style></head><body>
<h1>Aurora Swarm BTC — Operations Center</h1>
<p><strong>Assets · attestation · broadcast · identity · mines</strong></p>
<div class="card"><h2>Swarm Status</h2><div id="status">…</div><div id="btc_status" class="muted" style="margin-top:8px"></div></div>
<div class="card"><h2>Asset Transfer Manager</h2>
<div id="torrent_summary" class="muted"></div>
<div class="section"><input type="file" id="upload_file" style="width:auto"><input type="text" id="upload_name" placeholder="name"><label class="muted"><input type="checkbox" id="upload_anchor"> anchor</label>
<button id="upload_btn" onclick="uploadAsset()">Upload &amp; Announce</button></div>
<div class="section"><input type="text" id="ensure_infohash" placeholder="asset id"><button onclick="ensureAsset()">Ensure</button>
<button onclick="forceAnnounce()">Announce</button></div>
<div class="section"><button onclick="processBroadcasts()">Process queue</button>
<button onclick="processBatched()">Process batched (Merkle)</button>
<button onclick="registerIdentity()">Register identity</button>
<span id="queue_stats" class="muted"></span></div>
<div id="torrent_result" style="min-height:20px;margin:10px 0"></div>
<div class="section"><h3>Downloading</h3><div id="downloading_list">None</div></div>
<div class="section"><h3>Seeding</h3><div id="seeding_list">None</div></div>
</div>
<div class="card"><h2>Nodes</h2><pre id="nodes"></pre></div>
<div class="card"><h2>Events</h2><pre id="events"></pre></div>
<div class="card"><h2>Commands</h2>
<button onclick="sendBroadcast('pause')">Pause All</button>
<button onclick="sendBroadcast('resume')">Resume All</button>
<button onclick="sendBroadcast('adjust_intensity',1.0)">100%</button>
<input type="text" id="target_node" placeholder="node id">
<button onclick="sendToNode('pause')">Pause node</button>
<div id="command_result"></div></div>
<script>
function fmtSize(n){if(n==null)return'—';if(n<1024)return n+' B';if(n<1e6)return(n/1024).toFixed(1)+' KB';return(n/1e6).toFixed(1)+' MB'}
function showT(t,ok){const el=document.getElementById('torrent_result');el.innerText=t;el.className=ok?'success':'error'}
function anchorBadge(a){if(!a)return'';return `<span class="badge anchor">${a.status}</span>`}
async function refresh(){try{
 const s=await fetch('/status').then(r=>r.json());
 document.getElementById('status').innerHTML=`<div class="metric">${s.active_workers} workers</div><p>Entropy ${s.entropy} · ${s.total_ths} TH/s · ${s.mood}</p>`;
 try{const b=await fetch('/btc/status').then(r=>r.json());
  document.getElementById('btc_status').innerHTML=`BTC: net=${b.network} broadcaster=${b.broadcaster} pending=${b.pending_broadcasts} wallet=${(b.mining_wallet||'').slice(0,12)}…`+(b.identity?` · id=${b.identity.fingerprint}`:'');
 }catch(e){}
 document.getElementById('nodes').innerText=JSON.stringify(await fetch('/nodes').then(r=>r.json()),null,2);
 document.getElementById('events').innerText=JSON.stringify(await fetch('/events?limit=8').then(r=>r.json()),null,2);
 await refreshTorrent();
}catch(e){console.error(e)}}
function renderTable(items){if(!items||!items.length)return'<p class="muted">None</p>';let h='<table><tr><th>Name</th><th>Size</th><th>Progress</th><th>Status</th><th></th></tr>';
for(const t of items){const ih=t.infohash||'',pct=t.percent||0;
h+=`<tr><td><strong>${t.name||'—'}</strong><br><span class="mono muted">${ih.slice(0,16)}…</span></td><td>${fmtSize(t.size)}</td><td><div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>${pct}%</td><td>${t.complete?'<span class="badge ok">complete</span>':'<span class="badge warn">down</span>'}${anchorBadge(t.anchor)}${t.holder_count!=null?`<span class="badge">${t.holder_count} holders</span>`:''}</td><td>${t.complete?`<a href="/torrent/file/${ih}"><button class="small">DL</button></a> <button class="small" onclick="anchorAsset('${ih}')">Anchor</button> <button class="small" onclick="queueBroadcast('${ih}')">Broadcast</button>`:`<button class="small danger" onclick="cancelTorrent('${ih}')">Cancel</button>`}</td></tr>`}
return h+'</table>'}
async function refreshTorrent(){const data=await fetch('/torrent/status').then(r=>r.json());
document.getElementById('torrent_summary').innerHTML=`nodes=${data.torrent_capable_nodes} · down=${(data.downloading||[]).length} · seed=${(data.seeding||[]).length}`;
document.getElementById('downloading_list').innerHTML=renderTable(data.downloading||[]);
document.getElementById('seeding_list').innerHTML=renderTable(data.seeding||[]);
try{const q=await fetch('/torrent/broadcast_queue').then(r=>r.json());document.getElementById('queue_stats').textContent=(q.pending||0)+' pending'}catch(e){}}
async function uploadAsset(){const f=document.getElementById('upload_file');if(!f.files[0])return showT('file?',false);const fd=new FormData();fd.append('file',f.files[0]);const n=document.getElementById('upload_name').value.trim();if(n)fd.append('name',n);if(document.getElementById('upload_anchor').checked)fd.append('anchor','1');
const data=await fetch('/torrent/upload',{method:'POST',body:fd}).then(r=>r.json());showT(data.status==='ok'?`Seeded ${data.infohash.slice(0,12)}`:(data.detail||'fail'),data.status==='ok');setTimeout(refreshTorrent,500)}
async function ensureAsset(){const ih=document.getElementById('ensure_infohash').value.trim();if(!ih)return;const fd=new FormData();fd.append('infohash',ih);
const data=await fetch('/torrent/ensure',{method:'POST',body:fd}).then(r=>r.json());showT(data.status==='ok'?`Ensure ${ih.slice(0,12)}`:'fail',data.status==='ok')}
async function forceAnnounce(){const ih=document.getElementById('ensure_infohash').value.trim();const fd=new FormData();fd.append('infohash',ih);
const data=await fetch('/torrent/announce',{method:'POST',body:fd}).then(r=>r.json());showT(data.status==='ok'?'Announced':'fail',data.status==='ok')}
async function anchorAsset(ih){const fd=new FormData();fd.append('infohash',ih);const data=await fetch('/torrent/anchor',{method:'POST',body:fd}).then(r=>r.json());showT(data.status==='ok'?'Attested':'fail',data.status==='ok');setTimeout(refreshTorrent,400)}
async function queueBroadcast(ih){const fd=new FormData();fd.append('infohash',ih);const data=await fetch('/torrent/broadcast',{method:'POST',body:fd}).then(r=>r.json());showT(data.status==='ok'?'Queued':'fail',data.status==='ok');setTimeout(refreshTorrent,400)}
async function processBroadcasts(){const data=await fetch('/torrent/process_broadcasts',{method:'POST'}).then(r=>r.json());showT(data.status==='ok'?`Processed ${data.processed}`:(data.detail||'fail'),data.status==='ok');setTimeout(refreshTorrent,400)}
async function processBatched(){const data=await fetch('/torrent/process_broadcasts_batched',{method:'POST'}).then(r=>r.json());showT(data.status==='ok'?`Batch ${data.count||0} root=${(data.root||'').slice(0,12)}`:(data.detail||'fail'),data.status==='ok');setTimeout(refreshTorrent,400)}
async function registerIdentity(){const data=await fetch('/btc/identity/register',{method:'POST'}).then(r=>r.json());showT(data.status==='ok'?`Identity ${data.identity&&data.identity.fingerprint}`:(data.detail||'fail'),data.status==='ok');setTimeout(refresh,400)}
async function cancelTorrent(ih){const fd=new FormData();fd.append('infohash',ih);await fetch('/torrent/cancel',{method:'POST',body:fd});setTimeout(refreshTorrent,400)}
async function sendBroadcast(action,factor=null){const fd=new FormData();fd.append('action',action);if(factor!=null)fd.append('factor',factor);fd.append('reason','dash');
const data=await fetch('/command/broadcast',{method:'POST',body:fd}).then(r=>r.json());document.getElementById('command_result').innerText='✓ '+data.action}
async function sendToNode(action){const id=document.getElementById('target_node').value.trim();if(!id)return;const fd=new FormData();fd.append('action',action);fd.append('reason','dash');
const data=await fetch('/command/to_node/'+id,{method:'POST',body:fd}).then(r=>r.json());document.getElementById('command_result').innerText='✓ '+data.target}
refresh();setInterval(refresh,4000);
</script></body></html>"""
    return HTMLResponse(content=html)

try:
    from btc_ops import mount_btc_ops
    mount_btc_ops(app, get_anchor=get_anchor, get_identity=get_identity)
except Exception as _e:
    logger.debug(f"btc_ops not mounted: {_e}")

if __name__ == "__main__":
    get_torrent_manager()
    get_anchor()
    get_fabric()
    get_identity()
    uvicorn.run(app, host="0.0.0.0", port=8000)
