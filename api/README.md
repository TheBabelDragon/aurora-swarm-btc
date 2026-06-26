# Aurora Swarm BTC - External API

This folder contains a clean, versioned REST API that allows external systems to interact with the swarm.

## Why this approach?

- Modern (FastAPI + automatic OpenAPI docs)
- Versioned (`/api/v1/`)
- Secure by default (API Key auth, easy to upgrade to JWT)
- Easy to extend with new routers
- Works alongside existing Redis bus and Prometheus

## Running the API

```bash
uvicorn api.main:app --reload --port 8001
```

Then visit:
- http://localhost:8001/docs (Swagger UI)
- http://localhost:8001/redoc

## Authentication

All endpoints require the `X-API-Key` header.

Default key (change in production):
`aurora-swarm-secret-key-change-me`

## Current Endpoints (v1)

- `GET /api/v1/status/` - Swarm status
- `POST /api/v1/commands/` - Send commands to the swarm
- `GET /api/v1/metrics/` - Metrics summary

## Future Improvements

- WebSocket support for real-time events
- Better integration with Redis bus
- Role-based access control
- Rate limiting
