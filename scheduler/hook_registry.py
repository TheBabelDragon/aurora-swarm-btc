"""Simple Hook Registry for Aurora Swarm Mods.

Core exposes hooks that mods can subscribe to.
This allows extending behavior without modifying core files.
"""

from typing import Callable, Dict, List, Any

import logging

logger = logging.getLogger("aurora.hooks")


class HookRegistry:
    def __init__(self):
        self._hooks: Dict[str, List[Callable]] = {}

    def register(self, hook_name: str, func: Callable):
        if hook_name not in self._hooks:
            self._hooks[hook_name] = []
        self._hooks[hook_name].append(func)
        logger.info(f"Registered hook: {hook_name} -> {func.__name__}")

    def run(self, hook_name: str, *args, **kwargs) -> Any:
        if hook_name not in self._hooks:
            return None

        result = None
        for func in self._hooks[hook_name]:
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Hook {hook_name} failed in {func.__name__}: {e}")
        return result


# Global registry instance
registry = HookRegistry()


def register_hook(hook_name: str):
    """Decorator to easily register functions as hooks."""
    def decorator(func):
        registry.register(hook_name, func)
        return func
    return decorator
