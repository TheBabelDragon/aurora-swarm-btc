# Aurora Swarm BTC v1.0 — Final Production

**They yearn for the mines.**

Now with resilient integration to the WiFi CSI sensing system **and** an external API.

## External API

The swarm now exposes a clean, versioned REST API so external systems can plug in.

- Location: `api/main.py`
- Documentation: http://localhost:8001/docs (when running)
- Authentication: `X-API-Key` header

See `api/README.md` for details.

## Key Features

- Rich structured context sharing with sensing system
- Heartbeat monitoring + stale data detection
- Explicit integration health status
- Working PolicyEngine
- External API for third-party integration

**They do yearn. Now they have eyes, situational awareness, *and* an API.**