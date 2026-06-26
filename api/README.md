# Aurora Swarm BTC - External API (Near Full Connection)

This API is now substantially wired into the swarm.

## Key Capabilities

- Send real commands that are published to the Redis bus
- Get reasonably live status and metrics
- WebSocket endpoint that receives events when commands are sent
- Clean structure ready for further expansion

## Running

```bash
uvicorn api.main:app --port 8001
```

Visit `http://localhost:8001/docs` for interactive documentation.

## Notable Endpoints

- `POST /api/v1/commands/` → Publishes to Redis + broadcasts via WebSocket
- `GET /api/v1/status/`, `/metrics/`, `/workers/`, `/events/`
- WebSocket: `ws://localhost:8001/ws/events`

The API is now meaningfully connected to the swarm's internal systems.