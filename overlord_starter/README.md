# aurora-coordination (Private)

**Privileged coordination layer for the Aurora stack.**

This repository contains higher-privilege coordination logic, advanced policy engines, and the **Overlord / Throne Room** layer.

## Relationship to Public Repo

- Public: `aurora-swarm-btc` → Mesh foundation + node capabilities
- Private: `aurora-coordination` → Privileged coordination + Overlord Synergy

Communication between the two happens via the shared Redis mesh and well-defined message contracts.

## Key Directories

- `overlord/` — Throne Room / Highest privilege layer
- `coordination/` — General coordination logic
- `integration/` — Adapters to the public mesh

## Status

Initial structure created. Main expansion will happen in this private repository.
