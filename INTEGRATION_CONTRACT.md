# Sensing ↔ Swarm Integration Contract

This document defines the **official message contracts and resilience model** between:
- `aurora-swarm-btc` (this repo)
- `wifi-sensing-system` (TheBabelDragon/wifi-sensing-system)
- `metafield` (TheBabelDragon/metafield) — lattice / optical / ZVS intelligence layer

Together they form the **Aurora stack**: physical-spatial intelligence + mining swarm coordination + field-body sensing.

## Version
**1.2** (August 2026) — MetaField mesh publish path added. WiFi CSI contract unchanged.

## Channels (Shared Truth)

### Sensing → Swarm (wifi-sensing-system → aurora-swarm-btc)
- `aurora:sensing:context` → `FULL_CONTEXT_UPDATE` (tracks, events, behaviors, memory summary)
- `aurora:sensing:events`
- `aurora:sensing:alerts`
- Heartbeat key: `aurora:sensing:heartbeat`

### Swarm → Sensing (aurora-swarm-btc → wifi-sensing-system)
- Channel: `aurora:swarm:commands`

### MetaField ↔ Swarm (`mods/metafield_bridge`)
- `aurora:metafield:stats` — compact live snapshot (HMC, geometry, attractors, memory)
- `aurora:metafield:heartbeat` — `{timestamp, health, live}`
- `aurora:sensing:context.metafield` — merged object; **must not** wipe WiFi `tracks`

MetaField continues to *read* Aurora through `aurora_feed.py` (`aurora:sensing:context`, events, heartbeat). Publish from MetaField itself stays gated behind a control token. The Aurora-side bridge is the allowed publisher for file-exported stats.

Both sides should prefer publishing through their respective high-level layers when possible:
- `wifi-sensing-system` uses `SwarmBridge` + `AuroraAdapter`
- `aurora-swarm-btc` uses `CommsLayer` (recommended) or `SensingIntegration`
- MetaField file export: `meta_field_distributed.py --export-stats`
- Aurora file ingest: `mods/metafield_bridge`

## Resilience (Both Sides)

- Exponential backoff on Redis failures
- Heartbeat staleness detection
- Health status reporting
- Automatic reconnection
- Graceful degradation when the other side is unavailable
- MetaField bridge: file-only mode if Redis is down; no torch dependency on Aurora

## Mesh Participation (1.1+)

The WiFi sensing system is a **first-class citizen of the Comms Layer mesh**:
- Sensing components can register as nodes (type: `sensing`)
- Context updates and events are published via the mesh where possible
- Commands from the swarm scheduler can target sensing via `send_to_node` or broadcast

MetaField bodies should register as node type `metafield` when a live process exists. Until then the bridge reports `health=no_export` / `live=false`.

## Payload Expectations

See the detailed payload definitions and examples in:
- `wifi-sensing-system/INTEGRATION_CONTRACT.md`
- `wifi-sensing-system/bridges/swarm_bridge.py`
- `wifi-sensing-system/sensing/command_listener.py`
- `mods/metafield_bridge/README.md`
- MetaField `aurora_mods/metafield_sensing/`

## Implementation Notes

- `aurora-swarm-btc/sensing/integration.py` should align with `SwarmBridge` behavior
- `aurora-swarm-btc/comms/layer.py` is the preferred high-level interface for new code
- Both projects share the same Redis instance for the mesh
- CPU-only hosts are first-class: default miner backend is CPU (`AURORA_MINER_BACKEND=cpu`)

Contract Version: 1.2 (MetaField bridge)
