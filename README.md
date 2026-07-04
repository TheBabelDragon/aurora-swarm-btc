Add a short section about the new mod system at the end of the existing README.

## Mods System

The swarm now supports a clean mod system for experimental behavior.

- All new features and experiments should be developed as mods in `mods/`
- Core remains stable
- Mods attach via hooks (see `scheduler/hook_registry.py`)
- See `mods/README.md` for full documentation and development rules

Example mod: `thermal_aware_scheduler` (prioritizes cooler nodes)