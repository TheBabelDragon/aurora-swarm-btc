# Aurora Swarm BTC v1.0 — Final Production

**They yearn for the mines.**

Now with resilient sensing integration **and** a powerful external API.

## External API

The swarm exposes a clean, versioned REST + WebSocket API so external systems can integrate easily.

- Run with: `uvicorn api.main:app --port 8001`
- Docs: `http://localhost:8001/docs`
- Real-time events via WebSocket at `/ws/events`
- Commands are published to the Redis bus

See `api/README.md` for full details.

## Key Features

- Rich context sharing with WiFi CSI sensing system
- Heartbeat monitoring + graceful degradation
- External API with WebSocket support
- Working PolicyEngine + command routing

**They do yearn. Now they have eyes, a brain, a voice, *and* an API.**