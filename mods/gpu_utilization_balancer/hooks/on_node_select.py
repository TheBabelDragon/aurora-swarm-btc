"""GPU Utilization Balancer Mod

Filters out or deprioritizes nodes with high GPU utilization.
"""

from typing import List, Dict, Any


def on_node_select(nodes: List[Dict[str, Any]], task: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Deprioritize nodes with high GPU utilization (> 85% by default).
    """
    def utilization_key(node):
        util = node.get("gpu_utilization", 0)
        return util

    # Filter out extremely overloaded nodes
    filtered = [n for n in nodes if n.get("gpu_utilization", 0) < 90]

    if not filtered:
        # If all nodes are overloaded, return original list
        return nodes

    # Sort by utilization (lower is better)
    return sorted(filtered, key=utilization_key)
