# Aurora Swarm BTC v1.0 — Final Production

** They yearn for the mines. **

Now with resilient sensing integration ** and ** a powerful external API.

## Communications Layer (New)

Expanded with a dedicated **comms layer** (`comms/`) for clean, structured inter-component and swarm-wide communication.

- `CommsLayer`: High-level abstraction over Redis pub/sub + state
- Typed `SwarmMessage` (Pydantic)
- Node registration & discovery (heartbeats, active nodes)
- Convenience methods: `publish_event()`, `publish_telemetry()`, `send_command()`, `send_sensing_command()`
- Subscription handlers + listener loop
- Backward compatible with existing Redis channels

Usage example:
```python
from comms.layer import CommsLayer, SwarmMessage

layer = CommsLayer(node_id="worker-01")
layer.register_node(node_type="worker")
layer.publish_event("mining_started", {"hashrate": 120})
layer.send_sensing_command("adjust_gain", factor=1.2)
```

See `comms/layer.py` for full API and examples.

## External API

The swarm exposes a clean, versioned REST + WebSocket API so external systems can integrate easily.

- Run with: ` uvicorn api.main:app --port 8001 `
- Docs: ` http://localhost:8001/docs `
- Real-time events via WebSocket at ` /ws/events `
- Commands are published to the Redis bus

See ` api/README.md ` for full details.

## Key Features

- Rich context sharing with WiFi CSI sensing system
- Heartbeat monitoring + graceful degradation
- External API with WebSocket support
- Working PolicyEngine + command routing
- **New:** Structured Comms Layer for swarm coordination

** They do yearn. Now they have eyes, a brain, a voice, * an API *, **and a proper voice for talking to each other**. **