"""torrent_protocol Mod Entrypoint

Registers hooks so the rest of the swarm can trigger asset downloads
without knowing the internals of the torrent manager.
"""

from scheduler.hook_registry import registry
from mods.torrent_protocol.hooks.on_asset_needed import on_asset_needed


def register():
    registry.register("on_asset_needed", on_asset_needed)
    print("[MOD] torrent_protocol v0.2.0 registered — rarest-first + on_asset_needed ready")


if __name__ == "__main__":
    register()
