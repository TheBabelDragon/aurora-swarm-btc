# Mods System for Aurora Swarm

This directory contains all experimental and pluggable behavior for the swarm.

**Core Rule**: Never modify core logic directly for experiments. All new behavior starts here as a mod.

## Current Mods

- `thermal_aware_scheduler` — Prioritizes cooler nodes
- `gpu_utilization_balancer` — Avoids highly utilized GPUs
- `torrent_protocol` — In-mesh piece distribution (current Asset Fabric transport)
- `asset_fabric` — Content-addressed swarm Asset Fabric (`ensure` is the public verb)
- `btc_anchor` — Optional Bitcoin-style attestation for asset manifests

## Mod Structure

```
mods/
  <mod_name>/
    manifest.json
    entrypoint.py
    config.yaml (optional)
    hooks/
      on_*.py
    tasks/
    README.md
```

## How Mods Work

1. Core exposes hooks (e.g. `on_node_select`, `on_asset_needed`)
2. Enabled mods subscribe to relevant hooks via `entrypoint.py`
3. Mods can modify behavior before core continues execution

## Development Rules

- Always create a mod first
- Test in isolation
- Disable easily if unstable
- Only promote to core after long-term stability

See `scheduler/hook_registry.py` and `scheduler/node_selector.py` for how hooks are used.

### Asset & attestation direction

Prefer the `asset_fabric` language (`ensure`, `publish`, `possession`) for data-plane work.  
Use `btc_anchor` when a selected asset should gain an optional public commitment.  
`torrent_protocol` remains the piece-transport implementation underneath the fabric.
