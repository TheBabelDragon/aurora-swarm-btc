"""Thermal Aware Scheduler Mod

Prioritizes nodes with lower reported temperature.
"""

from typing import List, Dict, Any


def on_node_select(nodes: List[Dict[str, Any]], task: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Sort nodes by thermal reading (lower is better).
    Falls back gracefully if thermal data is missing.
    """
    def thermal_key(node):
        return node.get("thermal", 999)  # Default to very hot if unknown

    sorted_nodes = sorted(nodes, key=thermal_key)
    return sorted_nodes
