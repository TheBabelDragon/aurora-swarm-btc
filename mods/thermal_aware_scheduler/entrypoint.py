"""thermal_aware_scheduler Mod Entrypoint

Registers the mod's hooks with the core registry.
"""

from scheduler.hook_registry import registry

from .hooks.on_node_select import on_node_select


def register():
    registry.register("on_node_select", on_node_select)
    print("[MOD] thermal_aware_scheduler registered")


if __name__ == "__main__":
    register()
