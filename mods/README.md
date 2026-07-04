# Mods System for Aurora Swarm

This directory contains all experimental and pluggable behavior for the swarm.

**Core Rule**: Never modify core logic directly for experiments. All new behavior starts here as a mod.

## Mod Structure

```
mods/
  <mod_name>/
    manifest.json
    entrypoint.py
    config.yaml
    hooks/
      on_*.py
    tasks/
    README.md
```

## How Mods Work

1. Core exposes hooks (e.g. `on_node_select`)
2. Enabled mods subscribe to relevant hooks
3. Mods can modify behavior before core continues

## Current Mods

- (List will be maintained here)

## Development Rules

- Always create a mod first
- Test in isolation
- Disable easily if unstable
- Only promote to core after long-term stability
