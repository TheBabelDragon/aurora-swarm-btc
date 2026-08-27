"""mine_governor — register hooks + start agent."""

from __future__ import annotations


def register():
    try:
        from scheduler.hook_registry import registry

        from .hooks.on_node_select import on_node_select

        registry.register("on_node_select", on_node_select)
    except Exception:
        pass
    print("[MOD] mine_governor v0.2.0 registered — fleet commands can move this hasher")


def start(get_comms=None):
    if get_comms is None:
        return
    from .agent import start_governor

    start_governor(get_comms)


if __name__ == "__main__":
    register()
