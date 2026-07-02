# Aurora Swarm BTC v1.0 — Final Production

** They yearn for the mines. **

**This project + [wifi-sensing-system](https://github.com/TheBabelDragon/wifi-sensing-system) = the complete Aurora stack.**

Physical intelligence (WiFi CSI) + mining swarm coordination through a shared **Comms Layer mesh**.

## Quick Start - Control the Swarm

1. Start the dashboard:
   ```bash
   cd dashboard && python dashboard.py
   ```
   Open http://localhost:8000

2. Use the **Command Control** panel:
   - Broadcast fleet commands (scale intensity, pause, resume, restart)
   - Target individual workers by node ID

3. The scheduler runs autonomous logic (recovery, occupancy response, thermal management).

4. Workers execute real commands received via the mesh.

See `dashboard/dashboard.py` for the command endpoints and `worker/miner_worker.py` for execution logic.

## Deployment (Docker Compose)

### Control Plane (Recommended on main host)
```bash
cp .env.example .env
# Edit .env with your values

docker compose up -d --build
```

Access:
- Dashboard UI: http://your-host:8000
- API: http://your-host:8001

### Worker Plane (Run on other machines)
```bash
cp .env.example .env
# Set REDIS_URL to point to your control host
# Set WORKER_NAME, INTENSITY, etc.

docker compose -f docker-compose.worker.yml up -d --build
```

Workers will automatically join the mesh and appear in the dashboard.

See `docker-compose.yml` and `docker-compose.worker.yml` for details.

## Architecture Highlights

- `comms/layer.py` — The mesh (node registration, heartbeats, targeted + broadcast messaging, event history)
- Workers, scheduler, and sensing are first-class mesh participants
- Full bidirectional integration with `wifi-sensing-system`
- Live command & control UI in the dashboard

## Key Features

- Real WiFi CSI sensing integration
- Self-healing + environment-aware swarm
- Practical fleet control (intensity, pause, restart)
- Clean observability and manual override

** They do yearn. Now they have eyes, a brain, a voice, an API, **and you can actually control them from the browser**. **