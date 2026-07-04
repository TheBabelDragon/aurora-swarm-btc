"""gpu_utilization_balancer Mod Entrypoint

Registers the mod's hooks.
"""

from scheduler.hook_registry import registry

from .hooks.on_node_select import on_node_select


def register():
    registry.register("on_node_select", on_node_select)
    print("[MOD] gpu_utilization_balancer registered")


if __name__ == "__main__":
    register()
