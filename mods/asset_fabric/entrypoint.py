"""asset_fabric Mod Entrypoint

Registers the higher-level asset hooks so the rest of Aurora can speak
in ensure / possession language without knowing about pieces or torrents.
"""

from scheduler.hook_registry import registry


def register():
    # Re-export / alias the existing on_asset_needed so both names work.
    # The durable verb is "asset"; torrent remains an implementation detail.
    try:
        from mods.torrent_protocol.hooks.on_asset_needed import on_asset_needed

        registry.register("on_asset_needed", on_asset_needed)
        registry.register("on_asset_ensure", on_asset_needed)
    except Exception as e:
        # Redis / pydantic are optional at import time on a CPU smoke box.
        print(f"[MOD] asset_fabric: on_asset_needed deferred ({e.__class__.__name__})")

    print("[MOD] asset_fabric v0.1.0 registered — ensure() is the public verb")


if __name__ == "__main__":
    register()
