"""torrent_protocol Mod Entrypoint

Registers the torrent capability helpers and any relevant hooks.
"""

from scheduler.hook_registry import registry

# The manager itself is imported by workers / other components as needed.
# We keep the entrypoint lightweight so the mod can be loaded by any node type.

def register():
    # Future: register hooks here if we add torrent-specific scheduling logic
    # e.g. registry.register("on_asset_needed", on_asset_needed)
    print("[MOD] torrent_protocol registered — swarm-native piece distribution ready")


if __name__ == "__main__":
    register()
