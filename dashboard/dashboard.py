from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from control.bus import Bus
from comms.layer import CommsLayer, SwarmMessage
import uvicorn
import logging
import time
from typing import Optional, Dict, Any, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aurora-dashboard")

app = FastAPI(title="Aurora Swarm BTC — Comms Operations Center")
bus = Bus()
comms = CommsLayer(node_id="dashboard")

# Optional local TorrentManager so the dashboard can itself participate
# and serve as a convenient control point.
_torrent_manager = None

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
            _torrent_manager = False  # sentinel so we don't keep retrying
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
# TORRENT / ASSET SWARM API
# =====================================================================

@app.get("/torrent/status")
def torrent_status():
    """High-level torrent swarm health for the dashboard."""
    tm = get_torrent_manager()
    torrent_nodes = comms.get_nodes_by_capability("torrent") if hasattr(comms, "get_nodes_by_capability") else []

    local = []
    if tm:
        local = tm.list_torrents()

    # Also surface any announced torrents still living in Redis
    announced = []
    try:
        # Best-effort scan of known torrent keys (limited)
        keys = comms.r.keys("aurora:torrent:*") if hasattr(comms, "r") else []
        for k in keys[:40]:
            raw = comms.get_state(k.replace("aurora:", "", 1) if k.startswith("aurora:") else k)
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

    return {
        "torrent_capable_nodes": len(torrent_nodes),
        "local_torrents": local,
        "announced_torrents": announced,
        "dashboard_has_manager": tm is not None,
    }

@app.get("/torrent/list")
def torrent_list():
    tm = get_torrent_manager()
    if not tm:
        return {"torrents": [], "error": "TorrentManager not available on dashboard"}
    return {"torrents": tm.list_torrents()}

@app.post("/torrent/ensure")
async def torrent_ensure(infohash: str = Form(...), name: str = Form(None)):
    """Ask the swarm (and local manager) to ensure an asset is present."""
    infohash = infohash.strip().lower()
    if not infohash:
        return JSONResponse({"status": "error", "detail": "infohash required"}, status_code=400)

    # 1. Tell every manager via the mesh
    try:
        msg = SwarmMessage(
            type="asset.needed",
            payload={"infohash": infohash, "name": name or "", "source": "dashboard"},
            source=comms.node_id,
        )
        comms.publish_message("asset.needed", msg)
    except Exception as e:
        logger.warning(f"Failed to publish asset.needed: {e}")

    # 2. Also drive the local manager if we have one
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
    """Force-announce a local torrent (if the dashboard manager has it)."""
    tm = get_torrent_manager()
    if not tm:
        return JSONResponse({"status": "error", "detail": "No local TorrentManager"}, status_code=400)
    ok = tm.announce(infohash.strip().lower())
    return {"status": "ok" if ok else "failed", "infohash": infohash}

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
            .card { background: #111; border: 1px solid #0f0; padding: 20px; margin: 20px 0; border-radius: 8px; }
            pre { background: #000; padding: 15px; overflow-x: auto; font-size: 0.85em; }
            .metric { font-size: 2em; font-weight: bold; }
            button { background: #003300; color: #0f0; border: 1px solid #0f0; padding: 8px 16px; margin: 4px; cursor: pointer; border-radius: 4px; }
            button:hover { background: #005500; }
            .control-group { margin: 15px 0; }
            input { background: #000; color: #0f0; border: 1px solid #0f0; padding: 6px; margin: 4px; width: 280px; border-radius: 4px; }
            .success { color: #0f0; }
            .error { color: #f66; }
            .progress-bar { background: #222; border: 1px solid #0f0; height: 18px; border-radius: 4px; overflow: hidden; margin: 4px 0 10px 0; }
            .progress-fill { background: #0a0; height: 100%; transition: width 0.4s; }
            .torrent-row { border-bottom: 1px solid #1a1a1a; padding: 10px 0; }
            .torrent-row:last-child { border-bottom: none; }
            .muted { color: #6a6; font-size: 0.85em; }
            .badge { display: inline-block; background: #003300; border: 1px solid #0f0; padding: 2px 8px; border-radius: 10px; font-size: 0.75em; margin-left: 6px; }
            .badge.warn { background: #330; border-color: #aa0; color: #ff0; }
            .badge.ok { background: #030; border-color: #0f0; }
            table { width: 100%; border-collapse: collapse; }
            td, th { text-align: left; padding: 6px 8px; border-bottom: 1px solid #1a1a1a; }
            th { color: #6a6; font-weight: normal; font-size: 0.85em; }
        </style>
    </head>
    <body>
        <h1>🚀 Aurora Swarm BTC — Comms Operations Center</h1>
        <p><strong>They yearn for the mines... and now you can control them (and their assets).</strong></p>

        <div class="card">
            <h2>Swarm Status</h2>
            <div id="status">Loading...</div>
        </div>

        <!-- TORRENT / ASSET SWARM -->
        <div class="card">
            <h2>Torrent / Asset Swarm</h2>
            <div id="torrent_summary" class="muted">Loading torrent status…</div>

            <div style="margin: 16px 0;">
                <h3 style="margin-bottom: 8px;">Ensure Asset</h3>
                <input type="text" id="ensure_infohash" placeholder="infohash (e.g. a1b2c3d4…)">
                <input type="text" id="ensure_name" placeholder="optional name" style="width: 180px;">
                <button onclick="ensureAsset()">Ensure / Download</button>
                <button onclick="forceAnnounce()">Force Announce (local)</button>
            </div>

            <div id="torrent_result" style="min-height: 22px; margin-bottom: 12px;"></div>

            <h3>Active / Known Torrents</h3>
            <div id="torrent_list">Loading…</div>
        </div>

        <div class="card">
            <h2>Active Nodes (Mesh)</h2>
            <pre id="nodes">Loading...</pre>
        </div>

        <div class="card">
            <h2>Recent Events</h2>
            <pre id="events">Loading...</pre>
        </div>

        <!-- COMMAND CONTROL -->
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
                } catch(e) {
                    console.error(e);
                }
            }

            async function refreshTorrent() {
                try {
                    const data = await fetch('/torrent/status').then(r => r.json());
                    const summary = document.getElementById('torrent_summary');
                    summary.innerHTML =
                        `<span class="badge ok">${data.torrent_capable_nodes} torrent-capable nodes</span>` +
                        (data.dashboard_has_manager
                            ? ` <span class="badge ok">dashboard manager online</span>`
                            : ` <span class="badge warn">no local manager</span>`);

                    const listEl = document.getElementById('torrent_list');
                    const local = data.local_torrents || [];
                    const announced = data.announced_torrents || [];

                    if (local.length === 0 && announced.length === 0) {
                        listEl.innerHTML = `<p class="muted">No torrents known yet. Use “Ensure Asset” or create one on a worker.</p>`;
                        return;
                    }

                    let html = `<table><thead><tr>
                        <th>Name / Infohash</th><th>Progress</th><th>Have / Total</th><th>Status</th>
                    </tr></thead><tbody>`;

                    // Prefer local (richer) data
                    const seen = new Set();
                    for (const t of local) {
                        seen.add(t.infohash);
                        const pct = t.percent || 0;
                        const complete = t.complete;
                        const wanted = t.wanted;
                        html += `<tr class="torrent-row">
                            <td>
                                <strong>${t.name || '—'}</strong><br>
                                <span class="muted">${(t.infohash || '').slice(0, 16)}…</span>
                            </td>
                            <td style="min-width:160px;">
                                <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
                                ${pct}%
                            </td>
                            <td>${t.have || 0} / ${t.total || '?'}</td>
                            <td>
                                ${complete ? '<span class="badge ok">complete</span>' : '<span class="badge warn">downloading</span>'}
                                ${wanted && !complete ? '<span class="badge">wanted</span>' : ''}
                                ${t.pending ? `<span class="muted"> · ${t.pending} pending</span>` : ''}
                            </td>
                        </tr>`;
                    }

                    // Announced but not local
                    for (const t of announced) {
                        if (seen.has(t.infohash)) continue;
                        html += `<tr class="torrent-row">
                            <td>
                                <strong>${t.name || '—'}</strong><br>
                                <span class="muted">${(t.infohash || '').slice(0, 16)}…</span>
                            </td>
                            <td class="muted">announced only</td>
                            <td class="muted">${t.num_pieces || '?'} pieces</td>
                            <td><span class="badge">announced by ${t.created_by || '?'}</span></td>
                        </tr>`;
                    }

                    html += `</tbody></table>`;
                    listEl.innerHTML = html;
                } catch (e) {
                    console.error('torrent refresh failed', e);
                    document.getElementById('torrent_list').innerHTML =
                        `<p class="error">Could not load torrent status</p>`;
                }
            }

            async function ensureAsset() {
                const infohash = document.getElementById('ensure_infohash').value.trim();
                const name = document.getElementById('ensure_name').value.trim();
                if (!infohash) {
                    showTorrentResult('Enter an infohash first', false);
                    return;
                }
                const formData = new FormData();
                formData.append('infohash', infohash);
                if (name) formData.append('name', name);

                try {
                    const res = await fetch('/torrent/ensure', { method: 'POST', body: formData });
                    const data = await res.json();
                    if (data.status === 'ok') {
                        showTorrentResult(`✓ Ensure published for ${data.infohash.slice(0,12)}…`, true);
                        setTimeout(refreshTorrent, 800);
                    } else {
                        showTorrentResult(data.detail || 'Failed', false);
                    }
                } catch (e) {
                    showTorrentResult('Error calling ensure', false);
                }
            }

            async function forceAnnounce() {
                const infohash = document.getElementById('ensure_infohash').value.trim();
                if (!infohash) {
                    showTorrentResult('Enter an infohash first', false);
                    return;
                }
                const formData = new FormData();
                formData.append('infohash', infohash);
                try {
                    const res = await fetch('/torrent/announce', { method: 'POST', body: formData });
                    const data = await res.json();
                    showTorrentResult(data.status === 'ok' ? `✓ Announced ${infohash.slice(0,12)}…` : 'Announce failed (not local?)', data.status === 'ok');
                } catch (e) {
                    showTorrentResult('Error announcing', false);
                }
            }

            function showTorrentResult(text, success) {
                const el = document.getElementById('torrent_result');
                el.innerText = text;
                el.className = success ? 'success' : 'error';
                setTimeout(() => { el.innerText = ''; el.className = ''; }, 5000);
            }

            async function sendBroadcast(action, factor = null) {
                const formData = new FormData();
                formData.append('action', action);
                if (factor !== null) formData.append('factor', factor);
                formData.append('reason', 'manual_dashboard');

                try {
                    const res = await fetch('/command/broadcast', { method: 'POST', body: formData });
                    const data = await res.json();
                    showResult(`✓ Broadcast: ${data.action} → ${data.target}`, true);
                } catch(e) {
                    showResult('Error sending command', false);
                }
            }

            async function sendToNode(action, factor = null) {
                const nodeId = document.getElementById('target_node').value.trim();
                if (!nodeId) {
                    alert('Enter a target node ID (e.g. worker-01)');
                    return;
                }

                const formData = new FormData();
                formData.append('action', action);
                if (factor !== null) formData.append('factor', factor);
                formData.append('reason', 'manual_dashboard');

                try {
                    const res = await fetch(`/command/to_node/${nodeId}`, { method: 'POST', body: formData });
                    const data = await res.json();
                    showResult(`✓ Sent to ${data.target}: ${data.action}`, true);
                } catch(e) {
                    showResult('Error sending command', false);
                }
            }

            function showResult(text, success) {
                const el = document.getElementById('command_result');
                el.innerText = text;
                el.className = success ? 'success' : 'error';
                setTimeout(() => { el.innerText = ''; el.className = ''; }, 4500);
            }

            refresh();
            setInterval(refresh, 5000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

if __name__ == "__main__":
    # Warm the torrent manager on startup so the UI is immediately useful
    get_torrent_manager()
    uvicorn.run(app, host="0.0.0.0", port=8000)
