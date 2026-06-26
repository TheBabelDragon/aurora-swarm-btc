# Aurora Swarm BTC - External API

Clean, versioned, and extensible REST + WebSocket API for external integration.

## Features

- Versioned under `/api/v1/`
- Automatic OpenAPI documentation (`/docs`)
- API Key authentication
- WebSocket endpoint for real-time events (`/ws/events`)
- Public health check endpoint
- Easy to extend with new routers

## Running

```bash
uvicorn api.main:app --reload --port 8001
```

## Authentication

All protected endpoints require the header:
`X-API-Key: your-key-here`

## Current Endpoints (v1)

### Status
- `GET /api/v1/status/`

### Commands
- `POST /api/v1/commands/`

### Metrics
- `GET /api/v1/metrics/`

### Workers
- `GET /api/v1/workers/`

### Events
- `GET /api/v1/events/`

### Real-time
- WebSocket: `ws://localhost:8001/ws/events`

## Future Roadmap

- Better Redis integration for live data
- Rate limiting
- Role-based access
- More granular command validation
