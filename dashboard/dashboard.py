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
        "message": "They do yearn. Now with full Comms Layer + Torrent Swarm.",
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

# === Command API ===

@app.post("/command/broadcast")
async def broadcast_command(action: str = Form(...), factor: float = Form(None), reason: str = Form("manual")):
    payload = {"action": action}
    if factor is not None:
        payload["factor"] = factor
    if reason:
        payload["reason"] = reason
    comms.broadcast_to_workers(payload)
    logger.info(f"[DASH] Broadcast command: {action} factor={factor}")
    return {"status": "sent", "action": action, "target": "all_workers"}

@app.post("/command/to_node/{node_id}")
async def command_to_node(node_id: str, action: str = Form(...), factor: float = Form(None), reason: str = Form("manual")):
    payload = {"action": action}
    if factor is not None:
        payload["factor"] = factor
    if reason:
        payload["reason"] = reason
    comms.send_to_node(node_id, payload)
    logger.info(f"[DASH] Command to {node_id}: {action}")
    return {"status": "sent", "action": action, "target": node_id}

# =====================================================================
# ASSET TRANSFER MANAGER API
# =====================================================================

@app.get("/torrent/status")
def torrent_status():
    tm = get_torrent_manager()
    torrent_nodes = comms.get_nodes_by_capability("torrent") if hasattr(comms, "get_nodes_by_capability") else []

    local = []
    if tm:
        local = tm.list_torrents()
        # Enrich with size from meta when possible
        for t in local:
            meta = tm.torrents.get(t.get("infohash"))
            if meta:
                t["size"] = meta.size
                t["name"] = t.get("name") or meta.name

    announced = []
    try:
        keys = comms.r.keys("aurora:torrent:*") if hasattr(comms, "r") else []
        for k in keys[:60]:
            key = k.replace("aurora:", "", 1) if k.startswith("aurora:") else k
            raw = comms.get_state(key)
            if isinstance(raw, dict) and "infohash" in raw:
                announced.append({
                    "infohash": raw.get("infohash"),
                    "name": raw.get("name"),
                    "size": raw.get("size"),
                    "num_pieces": raw.get("num_pieces") or len(raw.get("piece_hashes", [])),
                    "created_by": raw.get("created_by"),
                })
    except Exception as e:
        logger.debug(f"Could not scan announced torrents: {e}")

    downloading = [t for t in local if not t.get("complete")]
    seeding = [t for t in local if t.get("complete")]

    return {
        "torrent_capable_nodes": len(torrent_nodes),
        "local_torrents": local,
        "downloading": downloading,
        "seeding": seeding,
        "announced_torrents": announced,
        "dashboard_has_manager": tm is not None,
    }

@app.get("/torrent/list")
def torrent_list():
    tm = get_torrent_manager()
    if not tm:
        return {"torrents": [], "error": "TorrentManager not available on dashboard"}
    return {"torrents": tm.list_torrents()}

@app.post("/torrent/upload")
async def torrent_upload(file: UploadFile = File(...), name: str = Form(None)):
    tm = get_torrent_manager()
    if not tm:
        return JSONResponse({"status": "error", "detail": "No local TorrentManager"}, status_code=400)
    if not file.filename:
        return JSONResponse({"status": "error", "detail": "No filename"}, status_code=400)

    safe_name = name or file.filename
    dest = UPLOAD_DIR / f"{int(time.time())}_{Path(file.filename).name}"
    try:
        content = await file.read()
        if len(content) == 0:
            return JSONResponse({"status": "error", "detail": "Empty file"}, status_code=400)
        dest.write_bytes(content)

        meta = tm.create_torrent(dest, name=safe_name)
        tm.announce(meta.infohash)

        logger.info(f"[DASH] Uploaded + announced {meta.infohash[:12]}… ({len(content)} bytes)")
        return {
            "status": "ok",
            "infohash": meta.infohash,
            "name": meta.name,
            "size": meta.size,
            "num_pieces": len(meta.piece_hashes),
        }
    except Exception as e:
        logger.exception("Upload/create torrent failed")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

@app.post("/torrent/ensure")
async def torrent_ensure(infohash: str = Form(...), name: str = Form(None)):
    infohash = infohash.strip().lower()
    if not infohash:
        return JSONResponse({"status": "error", "detail": "infohash required"}, status_code=400)

    try:
        msg = SwarmMessage(
            type="asset.needed",
            payload={"infohash": infohash, "name": name or "", "source": "dashboard"},
            source=comms.node_id,
        )
        comms.publish_message("asset.needed", msg)
    except Exception as e:
        logger.warning(f"Failed to publish asset.needed: {e}")

    tm = get_torrent_manager()
    local_result = None
    if tm:
        local_result = tm.ensure_asset(infohash=infohash, name=name)

    logger.info(f"[DASH] ensure_asset {infohash[:12]}… local={local_result}")
    return {
        "status": "ok",
        "infohash": infohash,
        "published_to_mesh": True,
        "local_manager": local_result is not None,
    }

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
    logger.info(f"[DASH] Cancelled / removed from wanted: {infohash[:12]}…")
    return {"status": "ok", "infohash": infohash}

@app.get("/torrent/file/{infohash}")
def torrent_file(infohash: str):
    """Download a completed asset from the dashboard node."""
    tm = get_torrent_manager()
    if not tm:
        return JSONResponse({"status": "error", "detail": "No local TorrentManager"}, status_code=400)
    infohash = infohash.strip().lower()
    path = tm.get_path(infohash)
    if not path or not path.exists():
        return JSONResponse({"status": "error", "detail": "File not found or not complete"}, status_code=404)
    meta = tm.torrents.get(infohash)
    filename = meta.name if meta else path.name
    return FileResponse(path, filename=filename, media_type="application/octet-stream")

@app.get("/healthz")
def healthz():
    return {"status": "healthy"}

@app.get("/", response_class=HTMLResponse)
def root():
    html = """
    <html>
    <head>
        <title>Aurora Swarm — Comms Operations Center</title>
        <style>
            body { font-family: system-ui, sans-serif; background: #0a0a0a; color: #0f0; margin: 40px; }
            h1 { color: #0f0; }
            h2 { color: #0f0; margin-top: 0; }
            h3 { color: #0c0; margin-bottom: 8px; }
            .card { background: #111; border: 1px solid #0f0; padding: 20px; margin: 20px 0; border-radius: 8px; }
            pre { background: #000; padding: 15px; overflow-x: auto; font-size: 0.85em; }
            .metric { font-size: 2em; font-weight: bold; }
            button { background: #003300; color: #0f0; border: 1px solid #0f0; padding: 7px 14px; margin: 3px; cursor: pointer; border-radius: 4px; font-size: 0.9em; }
            button:hover { background: #005500; }
            button:disabled { opacity: 0.5; cursor: not-allowed; }
            button.danger { background: #300; border-color: #f66; color: #f66; }
            button.danger:hover { background: #500; }
            button.small { padding: 4px 10px; font-size: 0.8em; }
            .control-group { margin: 15px 0; }
            input, input[type=file] { background: #000; color: #0f0; border: 1px solid #0f0; padding: 6px; margin: 4px; border-radius: 4px; }
            input[type=text] { width: 260px; }
            .success { color: #0f0; }
            .error { color: #f66; }
            .progress-bar { background: #222; border: 1px solid #0f0; height: 14px; border-radius: 4px; overflow: hidden; margin: 4px 0 4px 0; }
            .progress-fill { background: #0a0; height: 100%; transition: width 0.35s; }
            .muted { color: #6a6; font-size: 0.85em; }
            .badge { display: inline-block; background: #003300; border: 1px solid #0f0; padding: 2px 8px; border-radius: 10px; font-size: 0.75em; margin-left: 4px; }
            .badge.warn { background: #330; border-color: #aa0; color: #ff0; }
            .badge.ok { background: #030; border-color: #0f0; }
            table { width: 100%; border-collapse: collapse; margin-top: 8px; }
            td, th { text-align: left; padding: 8px 6px; border-bottom: 1px solid #1a1a1a; vertical-align: top; }
            th { color: #6a6; font-weight: normal; font-size: 0.8em; }
            .section { margin-top: 22px; }
            .empty { color: #555; font-style: italic; }
            .mono { font-family: ui-monospace, monospace; font-size: 0.85em; }
            .row-actions { white-space: nowrap; }
        </style>
    </head>
    <body>
        <h1>🚀 Aurora Swarm BTC — Comms Operations Center</h1>
        <p><strong>They yearn for the mines... and now you can move their assets.</strong></p>

        <div class="card">
            <h2>Swarm Status</h2>
            <div id="status">Loading...</div>
        </div>

        <div class="card">
            <h2>Asset Transfer Manager</h2>
            <div id="torrent_summary" class="muted">Loading…</div>

            <div class="section">
                <h3>Upload & Seed</h3>
                <p class="muted">Upload any file. Dashboard becomes the initial seeder and announces it to the mesh.</p>
                <input type="file" id="upload_file">
                <input type="text" id="upload_name" placeholder="optional display name">
                <button id="upload_btn" onclick="uploadAsset()">Upload & Announce</button>
            </div>

            <div class="section">
                <h3>Download by Infohash</h3>
                <p class="muted">Paste an infohash to pull an asset from the swarm onto this node (and tell every other manager too).</p>
                <input type="text" id="ensure_infohash" placeholder="infohash">
                <input type="text" id="ensure_name" placeholder="optional name" style="width:160px">
                <button onclick="ensureAsset()">Ensure / Download</button>
                <button onclick="forceAnnounce()">Force Announce</button>
            </div>

            <div id="torrent_result" style="min-height: 22px; margin: 12px 0;"></div>

            <div class="section">
                <h3>Downloading</h3>
                <div id="downloading_list" class="empty">None</div>
            </div>

            <div class="section">
                <h3>Seeding / Completed</h3>
                <div id="seeding_list" class="empty">None</div>
            </div>

            <div class="section">
                <h3>Announced on Mesh (not held here)</h3>
                <div id="announced_list" class="empty">None</div>
            </div>
        </div>

        <div class="card">
            <h2>Active Nodes (Mesh)</h2>
            <pre id="nodes">Loading...</pre>
        </div>

        <div class="card">
            <h2>Recent Events</h2>
            <pre id="events">Loading...</pre>
        </div>

        <div class="card">
            <h2>Command Control</h2>
            <div class="control-group">
                <h3>Broadcast Fleet Commands</h3>
                <button onclick="sendBroadcast('adjust_intensity', 0.85)">Scale Down 85%</button>
                <button onclick="sendBroadcast('adjust_intensity', 1.0)">Normal 100%</button>
                <button onclick="sendBroadcast('adjust_intensity', 1.15)">Scale Up 115%</button>
                <button onclick="sendBroadcast('pause')">Pause All</button>
                <button onclick="sendBroadcast('resume')">Resume All</button>
                <button onclick="sendBroadcast('restart_miner')">Restart All</button>
            </div>
            <div class="control-group">
                <h3>Target Specific Node</h3>
                <input type="text" id="target_node" placeholder="e.g. worker-01">
                <button onclick="sendToNode('pause')">Pause</button>
                <button onclick="sendToNode('resume')">Resume</button>
                <button onclick="sendToNode('restart_miner')">Restart</button>
                <button onclick="sendToNode('adjust_intensity', 0.9)">Set 90%</button>
            </div>
            <div id="command_result" style="margin-top: 15px; min-height: 24px;"></div>
        </div>

        <script>
            function fmtSize(n) {
                if (n === undefined || n === null) return '—';
                if (n < 1024) return n + ' B';
                if (n < 1048576) return (n/1024).toFixed(1) + ' KB';
                if (n < 1073741824) return (n/1048576).toFixed(1) + ' MB';
                return (n/1073741824).toFixed(2) + ' GB';
            }

            function copyText(text) {
                navigator.clipboard.writeText(text).then(() => {
                    showTorrentResult('Copied infohash', true);
                }).catch(() => {
                    showTorrentResult('Copy failed', false);
                });
            }

            async function refresh() {
                try {
                    const status = await fetch('/status').then(r => r.json());
                    document.getElementById('status').innerHTML =
                        `<div class="metric">${status.active_workers} workers</div>` +
                        `<p>Entropy: ${status.entropy} | Hashrate: ${status.total_ths} TH/s</p>` +
                        `<p>Mood: ${status.mood}</p>`;

                    const nodes = await fetch('/nodes').then(r => r.json());
                    document.getElementById('nodes').innerText = JSON.stringify(nodes, null, 2);

                    const events = await fetch('/events?limit=10').then(r => r.json());
                    document.getElementById('events').innerText = JSON.stringify(events, null, 2);

                    await refreshTorrent();
                } catch(e) { console.error(e); }
            }

            function renderTorrentTable(items, mode) {
                if (!items || items.length === 0) return '<p class="empty">None</p>';
                let html = `<table><thead><tr>
                    <th>Name / Infohash</th><th>Size</th><th>Progress</th><th>Pieces</th><th>Status</th><th></th>
                </tr></thead><tbody>`;
                for (const t of items) {
                    const pct = t.percent || 0;
                    const complete = !!t.complete;
                    const ih = t.infohash || '';
                    html += `<tr>
                        <td>
                            <strong>${t.name || '—'}</strong><br>
                            <span class="mono muted">${ih.slice(0,20)}${ih.length>20?'…':''}</span>
                            <button class="small" onclick="copyText('${ih}')">Copy</button>
                        </td>
                        <td>${fmtSize(t.size)}</td>
                        <td style="min-width:130px">
                            <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
                            ${pct}%
                        </td>
                        <td>${t.have||0} / ${t.total||'?'}</td>
                        <td>
                            ${complete ? '<span class="badge ok">complete</span>' : '<span class="badge warn">downloading</span>'}
                            ${t.wanted && !complete ? '<span class="badge">wanted</span>' : ''}
                            ${t.pending ? `<span class="muted"> · ${t.pending} pending</span>` : ''}
                        </td>
                        <td class="row-actions">
                            ${!complete ? `<button class="danger small" onclick="cancelTorrent('${ih}')">Cancel</button>` : ''}
                            ${complete ? `
                                <a href="/torrent/file/${ih}"><button class="small">Download</button></a>
                                <button class="small" onclick="forceAnnounceHash('${ih}')">Re-announce</button>
                            ` : ''}
                        </td>
                    </tr>`;
                }
                html += '</tbody></table>';
                return html;
            }

            async function refreshTorrent() {
                try {
                    const data = await fetch('/torrent/status').then(r => r.json());
                    document.getElementById('torrent_summary').innerHTML =
                        `<span class="badge ok">${data.torrent_capable_nodes} torrent nodes</span>` +
                        (data.dashboard_has_manager
                            ? ' <span class="badge ok">manager online</span>'
                            : ' <span class="badge warn">no local manager</span>') +
                        ` <span class="muted">· ${(data.downloading||[]).length} downloading · ${(data.seeding||[]).length} seeding</span>`;

                    document.getElementById('downloading_list').innerHTML = renderTorrentTable(data.downloading || [], 'down');
                    document.getElementById('seeding_list').innerHTML = renderTorrentTable(data.seeding || [], 'seed');

                    const localHashes = new Set((data.local_torrents || []).map(t => t.infohash));
                    const onlyAnnounced = (data.announced_torrents || []).filter(t => !localHashes.has(t.infohash));
                    if (onlyAnnounced.length === 0) {
                        document.getElementById('announced_list').innerHTML = '<p class="empty">None</p>';
                    } else {
                        let html = '<table><thead><tr><th>Name</th><th>Size</th><th>Infohash</th><th>Pieces</th><th>By</th><th></th></tr></thead><tbody>';
                        for (const t of onlyAnnounced) {
                            const ih = t.infohash || '';
                            const safeName = (t.name || '').replace(/'/g, "");
                            html += `<tr>
                                <td>${t.name || '—'}</td>
                                <td>${fmtSize(t.size)}</td>
                                <td class="mono muted">${ih.slice(0,18)}… <button class="small" onclick="copyText('${ih}')">Copy</button></td>
                                <td>${t.num_pieces || '?'}</td>
                                <td class="muted">${t.created_by || '?'}</td>
                                <td><button class="small" onclick="ensureHash('${ih}', '${safeName}')">Download</button></td>
                            </tr>`;
                        }
                        html += '</tbody></table>';
                        document.getElementById('announced_list').innerHTML = html;
                    }
                } catch (e) {
                    console.error(e);
                    document.getElementById('downloading_list').innerHTML = '<p class="error">Failed to load</p>';
                }
            }

            async function uploadAsset() {
                const fileInput = document.getElementById('upload_file');
                const name = document.getElementById('upload_name').value.trim();
                const btn = document.getElementById('upload_btn');
                if (!fileInput.files || !fileInput.files[0]) {
                    showTorrentResult('Choose a file first', false);
                    return;
                }
                const formData = new FormData();
                formData.append('file', fileInput.files[0]);
                if (name) formData.append('name', name);

                btn.disabled = true;
                showTorrentResult('Uploading & creating torrent…', true);
                try {
                    const res = await fetch('/torrent/upload', { method: 'POST', body: formData });
                    const data = await res.json();
                    if (data.status === 'ok') {
                        showTorrentResult(`✓ Seeded “${data.name}” → ${data.infohash.slice(0,12)}… (${fmtSize(data.size)}, ${data.num_pieces} pieces)`, true);
                        fileInput.value = '';
                        document.getElementById('upload_name').value = '';
                        setTimeout(refreshTorrent, 500);
                    } else {
                        showTorrentResult(data.detail || 'Upload failed', false);
                    }
                } catch (e) {
                    showTorrentResult('Upload error', false);
                } finally {
                    btn.disabled = false;
                }
            }

            async function ensureAsset() {
                const infohash = document.getElementById('ensure_infohash').value.trim();
                const name = document.getElementById('ensure_name').value.trim();
                if (!infohash) { showTorrentResult('Enter an infohash', false); return; }
                await ensureHash(infohash, name);
            }

            async function ensureHash(infohash, name) {
                const formData = new FormData();
                formData.append('infohash', infohash);
                if (name) formData.append('name', name);
                try {
                    const res = await fetch('/torrent/ensure', { method: 'POST', body: formData });
                    const data = await res.json();
                    if (data.status === 'ok') {
                        showTorrentResult(`✓ Ensure published for ${data.infohash.slice(0,12)}…`, true);
                        setTimeout(refreshTorrent, 600);
                    } else {
                        showTorrentResult(data.detail || 'Failed', false);
                    }
                } catch (e) {
                    showTorrentResult('Error', false);
                }
            }

            async function forceAnnounce() {
                const infohash = document.getElementById('ensure_infohash').value.trim();
                if (!infohash) { showTorrentResult('Enter an infohash', false); return; }
                await forceAnnounceHash(infohash);
            }

            async function forceAnnounceHash(infohash) {
                const formData = new FormData();
                formData.append('infohash', infohash);
                try {
                    const res = await fetch('/torrent/announce', { method: 'POST', body: formData });
                    const data = await res.json();
                    showTorrentResult(data.status === 'ok' ? `✓ Announced ${infohash.slice(0,12)}…` : 'Announce failed (not local?)', data.status === 'ok');
                } catch (e) {
                    showTorrentResult('Error', false);
                }
            }

            async function cancelTorrent(infohash) {
                const formData = new FormData();
                formData.append('infohash', infohash);
                try {
                    const res = await fetch('/torrent/cancel', { method: 'POST', body: formData });
                    const data = await res.json();
                    showTorrentResult(data.status === 'ok' ? `Cancelled ${infohash.slice(0,12)}…` : 'Cancel failed', data.status === 'ok');
                    setTimeout(refreshTorrent, 400);
                } catch (e) {
                    showTorrentResult('Error', false);
                }
            }

            function showTorrentResult(text, success) {
                const el = document.getElementById('torrent_result');
                el.innerText = text;
                el.className = success ? 'success' : 'error';
                setTimeout(() => { if (el.innerText === text) { el.innerText = ''; el.className = ''; } }, 7000);
            }

            async function sendBroadcast(action, factor = null) {
                const formData = new FormData();
                formData.append('action', action);
                if (factor !== null) formData.append('factor', factor);
                formData.append('reason', 'manual_dashboard');
                try {
                    const res = await fetch('/command/broadcast', { method: 'POST', body: formData });
                    const data = await res.json();
                    showResult(`✓ Broadcast: ${data.action}`, true);
                } catch(e) { showResult('Error', false); }
            }

            async function sendToNode(action, factor = null) {
                const nodeId = document.getElementById('target_node').value.trim();
                if (!nodeId) { alert('Enter a target node ID'); return; }
                const formData = new FormData();
                formData.append('action', action);
                if (factor !== null) formData.append('factor', factor);
                formData.append('reason', 'manual_dashboard');
                try {
                    const res = await fetch(`/command/to_node/${nodeId}`, { method: 'POST', body: formData });
                    const data = await res.json();
                    showResult(`✓ Sent to ${data.target}: ${data.action}`, true);
                } catch(e) { showResult('Error', false); }
            }

            function showResult(text, success) {
                const el = document.getElementById('command_result');
                el.innerText = text;
                el.className = success ? 'success' : 'error';
                setTimeout(() => { el.innerText = ''; el.className = ''; }, 4500);
            }

            refresh();
            setInterval(refresh, 3500);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

if __name__ == "__main__":
    get_torrent_manager()
    uvicorn.run(app, host="0.0.0.0", port=8000)
