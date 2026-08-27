"""Aurora comms — import submodules directly (layer needs redis)."""

__all__ = ["CommsLayer", "SwarmMessage"]


def __getattr__(name: str):
    if name in ("CommsLayer", "SwarmMessage"):
        from .layer import CommsLayer, SwarmMessage

        return CommsLayer if name == "CommsLayer" else SwarmMessage
    raise AttributeError(name)
