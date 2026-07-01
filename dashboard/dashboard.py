from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from control.bus import Bus
from comms.layer import CommsLayer
import uvicorn
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aurora-dashboard")

app = FastAPI(title="Aurora Swarm BTC — Comms Operations Center")
bus = Bus()
comms = CommsLayer(node_id="dashboard")

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
        "message": "They do yearn. Now with full Comms Layer.",
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
            .card { background: #111; border: 1px solid #0f0; padding: 20px; margin: 20px 0; border-radius: 8px; }
            pre { background: #000; padding: 15px; overflow-x: auto; }
            .metric { font-size: 2em; font-weight: bold; }
            button { background: #003300; color: #0f0; border: 1px solid #0f0; padding: 8px 16px; margin: 4px; cursor: pointer; }
            button:hover { background: #005500; }
            .control-group { margin: 15px 0; }
            input { background: #000; color: #0f0; border: 1px solid #0f0; padding: 6px; margin: 4px; width: 220px; }
            .success { color: #0f0; }
            .error { color: #f66; }
        </style>
    </head>
    <body>
        <h1>🚀 Aurora Swarm BTC — Comms Operations Center</h1>
        <p><strong>They yearn for the mines... and now you can control them.</strong></p>

        <div class="card">
            <h2>Swarm Status</h2>
            <div id="status">Loading...</div>
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
                } catch(e) {
                    console.error(e);
                }
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
