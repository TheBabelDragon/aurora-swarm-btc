# Mods System for Aurora Swarm

**Core Rule**: Never modify core logic directly for experiments. All new behavior starts here as a mod.

## Current Mods

- `thermal_aware_scheduler` — Prioritizes cooler nodes
- `gpu_utilization_balancer` — Avoids highly utilized GPUs
- `torrent_protocol` — Piece transport for Asset Fabric
- `asset_fabric` — Content-addressed swarm assets
- `btc_anchor` — Bitcoin attestation
- `btc_identity` — Bitcoin-style node identity
- `ln_tips` — Lightning seeder tips
- `bvl` — **Babel Value Ledger** (mesh-native swarm credits)

## Direction

`asset_fabric` for data · `btc_anchor` for attestation · `btc_identity` for labels ·  
`bvl` for internal value · `ln_tips` for sat settlement of that value.
