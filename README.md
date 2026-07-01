# Aurora Swarm BTC v1.0 — Final Production

** They yearn for the mines. **

**This project + [wifi-sensing-system](https://github.com/TheBabelDragon/wifi-sensing-system) together form the complete Aurora stack.**

WiFi CSI spatial intelligence (from `wifi-sensing-system`) + entropy-driven mining swarm coordination (this repo) communicate through the shared **Comms Layer mesh**.

## Communications Layer (Mesh) + Sensing Synergy

The `comms/` layer is the shared nervous system.

- Both projects publish/consume through Redis + high-level abstractions
- `wifi-sensing-system` uses `SwarmBridge` + `AuroraAdapter`
- `aurora-swarm-btc` uses `CommsLayer` (workers, scheduler, and now sensing all participate)
- Sensing is a first-class mesh node (type: `sensing`)
- Full bidirectional command + context flow

See `INTEGRATION_CONTRACT.md` (v1.1 - Maximum Alignment) and `sensing/integration.py`.

## External API

Fully integrated with the mesh.

See `api/README.md`.

## Key Features

- Real WiFi CSI sensing integration (via paired `wifi-sensing-system`)
- Self-healing worker mesh with dynamic discovery
- Policy-driven actions from physical context
- Production Comms Operations Center dashboard

** They do yearn. Now they have eyes (CSI), a brain (policy + mesh), a voice, an API, **and they coordinate as one living system**. **