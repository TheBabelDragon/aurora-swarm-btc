# Sensing ↔ Swarm Integration Contract

This document defines the message contracts and resilience model between aurora-swarm-btc and the WiFi CSI Spatial Intelligence System.

## Channels

### Receiving from Sensing
- `aurora:sensing:context` (rich context)
- `aurora:sensing:events`
- `aurora:sensing:alerts`
- Heartbeat key: `aurora:sensing:heartbeat`

### Sending to Sensing
- Channel: `aurora:swarm:commands`

See the main contract document in the wifi-sensing-system repo for full payload definitions.

## Resilience
- `SensingIntegration` implements heartbeat staleness detection
- Automatic reconnection on Redis failures
- Graceful degradation when sensing is unavailable
- Health status available via `get_health_status()`

## Current Limitations
- Commands are unauthenticated
- For trusted environments only

Contract Version: 1.0 (June 2026)