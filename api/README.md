# Aurora Swarm BTC - External API

The API is fully wired into the swarm via the Comms Layer mesh.

## Key Capabilities

- Send commands that flow through `CommsLayer` (targeted or broadcast)
- Get live status, metrics, and active workers from the node registry
- WebSocket real-time event stream (events published via mesh)
- Clean, versioned, documented surface for external systems

## Running

```bash
uvicorn api.main:app --port 8001
```

Interactive docs: `http://localhost:8001/docs`

## Endpoints

- `POST /api/v1/commands/` — publishes via CommsLayer
- `GET /api/v1/status/`, `/metrics/`, `/workers/`, `/events/` — dynamic data from mesh + Redis
- WebSocket: `ws://localhost:8001/ws/events`

All routers now consume the `CommsLayer` for dynamic worker discovery, event history, and telemetry.

See `comms/layer.py` for the mesh implementation.