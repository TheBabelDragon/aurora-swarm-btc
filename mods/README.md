# Mods System for Aurora Swarm

**Core Rule**: Never modify core logic directly for experiments. All new behavior starts here as a mod.

## Current Mods

- `thermal_aware_scheduler` — Prioritizes cooler nodes
- `gpu_utilization_balancer` — Avoids highly utilized GPUs
- `torrent_protocol` — Piece transport for Asset Fabric
- `asset_fabric` — Content-addressed swarm assets
- `btc_anchor` — Bitcoin attestation (commitments, Merkle batches, CLI/log writer)
- `btc_identity` — Bitcoin-style node identity
- `ln_tips` — Lightning seeder tips (ledger + pluggable tipper)

## Direction

Prefer `asset_fabric` for data-plane work.  
`btc_anchor` for optional public attestation.  
`btc_identity` for stable node labels.  
`ln_tips` for soft incentives to seeders.
