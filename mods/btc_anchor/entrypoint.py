"""btc_anchor Mod Entrypoint"""

from scheduler.hook_registry import registry


def register():
    # No mandatory hooks yet — the service is called explicitly from
    # AssetFabric or control-plane code. Future: auto-anchor on publish.
    print("[MOD] btc_anchor v0.1.0 registered — asset attestation ready")


if __name__ == "__main__":
    register()
