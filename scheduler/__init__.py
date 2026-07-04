"""Scheduler Package

Exposes the hook-aware node selector and makes mod integration easy.

Usage:
    from scheduler import select_node

    selected = select_node(available_nodes, task)
"""

from .node_selector import select_node

from mods.loader import load_mods

# Auto-load enabled mods when the scheduler package is imported
load_mods()
