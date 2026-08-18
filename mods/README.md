# Mods System for Aurora Swarm

This directory contains all experimental and pluggable behavior for the swarm.

**Core Rule**: Never modify core logic directly for experiments. All new behavior starts here as a mod.

## Current Mods

- `thermal_aware_scheduler` — Prioritizes cooler nodes
- `gpu_utilization_balancer` — Avoids highly utilized GPUs
- `torrent_protocol` — In-mesh piece distribution (Asset Fabric transport)
- `asset_fabric` — Content-addressed swarm assets (`ensure` / `publish` / `possession`)
- `btc_anchor` — Bitcoin attestation (commitments, Merkle batches, broadcast queue)
- `btc_identity` — Bitcoin-style node identity (keys, fingerprints, signed claims)

## Development Rules

- Always create a mod first
- Test in isolation
- Disable easily if unstable
- Only promote to core after long-term stability

### Asset & Bitcoin direction

Prefer `asset_fabric` for data-plane work.  
Use `btc_anchor` for optional public attestation (single or batched).  
Use `btc_identity` when nodes should carry stable cryptographic labels on the mesh.
