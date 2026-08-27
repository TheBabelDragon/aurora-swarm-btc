"""Simple Hook Registry for Aurora Swarm Mods.

Core exposes hooks that mods can subscribe to.
This allows extending behavior without modifying core files.
"""

from typing import Any, Callable, Dict, List

import logging

logger = logging.getLogger("aurora.hooks")


class HookRegistry:
    def __init__(self):
        self._hooks: Dict[str, List[Callable]] = {}

    def register(self, hook_name: str, func: Callable):
        if hook_name not in self._hooks:
            self._hooks[hook_name] = []
        self._hooks[hook_name].append(func)
        logger.info("Registered hook: %s -> %s", hook_name, getattr(func, "__name__", func))

    def run(self, hook_name: str, *args, **kwargs) -> Any:
        """Run hooks in registration order.

        If a hook returns a value and the first positional argument is a
        list/dict, that value is forwarded as the first argument to the
        next hook so mods can compose (filter/reorder) instead of clobber.
        """
        if hook_name not in self._hooks:
            return None

        result = None
        current_args = list(args)
        for func in self._hooks[hook_name]:
            try:
                result = func(*current_args, **kwargs)
                if result is not None and current_args:
                    current_args[0] = result
            except Exception as e:
                logger.error("Hook %s failed in %s: %s", hook_name, getattr(func, "__name__", func), e)
        return result


# Global registry instance
registry = HookRegistry()


def register_hook(hook_name: str):
    """Decorator to easily register functions as hooks."""

    def decorator(func):
        registry.register(hook_name, func)
        return func

    return decorator
