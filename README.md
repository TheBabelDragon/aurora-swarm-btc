# Aurora Swarm BTC v1.0 — Final Production

** They yearn for the mines. **

The swarm runs on a living **Comms Layer mesh**. Every node (workers, scheduler, sensing, API) participates: self-registers, heartbeats, publishes telemetry/events, and can send/receive targeted messages.

## Communications Layer (Mesh)

`comms/` is the central nervous system of the node grid.

- `CommsLayer`: Mesh-aware abstraction (Redis backbone + node registry + targeted messaging)
- Every node joins via `register_node()` + `heartbeat()`
- `send_to_node()`, `broadcast_to_workers()`, event history
- Typed `SwarmMessage`
- Full backward compatibility with existing channels

**The mining nodes themselves perpetuate the mesh.**

See `comms/layer.py` and `worker/miner_worker.py` for the implementation.

## External API

Fully integrated with the mesh.

- `uvicorn api.main:app --port 8001`
- Live data from node registry and event history
- WebSocket at `/ws/events`

See `api/README.md`.

## Key Features

- WiFi CSI sensing integration with policy-driven actions
- Self-healing worker mesh (registration + heartbeats)
- Dynamic discovery of active nodes
- Real-time events and telemetry via CommsLayer
- Production dashboard (Comms Operations Center)

** They do yearn. Now they have eyes, a brain, a voice, an API, **and they talk to each other in a living mesh**. **