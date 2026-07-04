"""Node Selector with Mod Hook Support.

This provides a clean extension point for scheduler mods.
"""

from typing import List, Dict, Any

import logging

from .hook_registry import registry

logger = logging.getLogger("aurora.scheduler")


def select_node(nodes: List[Dict[str, Any]], task: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Select the best node for a task.

    Runs registered 'on_node_select' hooks from mods,
    allowing them to filter/reorder the node list.
    """
    if not nodes:
        raise ValueError("No nodes available")

    # Allow mods to modify the node list (filter, sort, etc.)
    modified_nodes = registry.run("on_node_select", nodes, task) or nodes

    if not modified_nodes:
        logger.warning("All nodes filtered out by mods. Falling back to original list.")
        modified_nodes = nodes

    # Default behavior: pick the first node after mod processing
    selected = modified_nodes[0]

    logger.info(f"Selected node: {selected.get('id', selected)}")
    return selected
