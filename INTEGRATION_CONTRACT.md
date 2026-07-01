# Sensing ↔ Swarm Integration Contract

This document defines the **official message contracts and resilience model** between:
- `aurora-swarm-btc` (this repo)
- `wifi-sensing-system` (TheBabelDragon/wifi-sensing-system)

Together they form the full **Aurora stack** for physical-spatial intelligence + mining swarm coordination.

## Version
**1.1** (June 2026) - Maximum alignment with wifi-sensing-system bridges + CommsLayer mesh participation

## Channels (Shared Truth)

### Sensing → Swarm (wifi-sensing-system → aurora-swarm-btc)
- `aurora:sensing:context` → `FULL_CONTEXT_UPDATE` (tracks, events, behaviors, memory summary)
- `aurora:sensing:events`
- `aurora:sensing:alerts`
- Heartbeat key: `aurora:sensing:heartbeat`

### Swarm → Sensing (aurora-swarm-btc → wifi-sensing-system)
- Channel: `aurora:swarm:commands`

Both sides should prefer publishing through their respective high-level layers when possible:
- `wifi-sensing-system` uses `SwarmBridge` + `AuroraAdapter`
- `aurora-swarm-btc` uses `CommsLayer` (recommended) or `SensingIntegration`

## Resilience (Both Sides)

- Exponential backoff on Redis failures
- Heartbeat staleness detection
- Health status reporting
- Automatic reconnection
- Graceful degradation when the other side is unavailable

## Mesh Participation (New in 1.1)

The WiFi sensing system is now a **first-class citizen of the Comms Layer mesh**:
- Sensing components can register as nodes (type: `sensing`)
- Context updates and events are published via the mesh where possible
- Commands from the swarm scheduler can target sensing via `send_to_node` or broadcast

## Payload Expectations

See the detailed payload definitions and examples in:
- `wifi-sensing-system/INTEGRATION_CONTRACT.md`
- `wifi-sensing-system/bridges/swarm_bridge.py`
- `wifi-sensing-system/sensing/command_listener.py`

## Implementation Notes

- `aurora-swarm-btc/sensing/integration.py` should align with `SwarmBridge` behavior
- `aurora-swarm-btc/comms/layer.py` is the preferred high-level interface for new code
- Both projects share the same Redis instance for the mesh

Contract Version: 1.1 (Maximum Alignment)