from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
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
    """Live swarm nodes from CommsLayer registry."""
    return {"nodes": comms.get_active_nodes()}

@app.get("/events")
def get_events(limit: int = 20):
    """Recent events from CommsLayer history."""
    return {"events": comms.get_recent_events(limit)}

@app.get("/comms-health")
def comms_health():
    return {
        "comms_layer": "operational",
        "node_id": comms.node_id,
        "active_nodes": len(comms.get_active_nodes()),
        "recent_events_count": len(comms.get_recent_events(5))
    }

@app.get("/healthz")
def healthz():
    return {"status": "healthy"}

@app.get("/", response_class=HTMLResponse)
def root():
    """Simple HTML UI for the Comms Operations Center (better draw than raw mining stats)."""
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
        </style>
    </head>
    <body>
        <h1>🚀 Aurora Swarm BTC — Comms Operations Center</h1>
        <p><strong>They yearn for the mines... and now they talk to each other.</strong></p>
        
        <div class="card">
            <h2>Swarm Status</h2>
            <div id="status">Loading...</div>
        </div>
        
        <div class="card">
            <h2>Active Nodes (Comms Registry)</h2>
            <pre id="nodes">Loading...</pre>
        </div>
        
        <div class="card">
            <h2>Recent Events (Comms History)</h2>
            <pre id="events">Loading...</pre>
        </div>
        
        <script>
            async function refresh() {
                const status = await fetch('/status').then(r => r.json());
                document.getElementById('status').innerHTML = 
                    `<div class="metric">${status.active_workers} workers</div>` +
                    `<p>Entropy: ${status.entropy} | Hashrate: ${status.total_ths} TH/s</p>` +
                    `<p>Mood: ${status.mood}</p>`;
                
                const nodes = await fetch('/nodes').then(r => r.json());
                document.getElementById('nodes').innerText = JSON.stringify(nodes, null, 2);
                
                const events = await fetch('/events?limit=10').then(r => r.json());
                document.getElementById('events').innerText = JSON.stringify(events, null, 2);
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
