"""mine_governor — register + optional standalone start."""

from __future__ import annotations


def register():
    print("[MOD] mine_governor v0.1.0 registered — fleet commands can move this hasher")


def start(get_comms=None):
    if get_comms is None:
        return
    from .agent import start_governor

    start_governor(get_comms)


if __name__ == "__main__":
    register()
