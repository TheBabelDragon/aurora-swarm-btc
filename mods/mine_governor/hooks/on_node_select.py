"""Prefer nodes that advertise mine_governor when the task is mining."""

from __future__ import annotations

from typing import Any, List


def on_node_select(node_list: List[Any], task_type=None, **kwargs):
    if task_type not in ("mining", "mine", "hash"):
        return node_list
    gov, other = [], []
    for n in node_list or []:
        caps = []
        if isinstance(n, dict):
            caps = n.get("capabilities") or []
            meta = n.get("metadata") or {}
            if meta.get("governor") or "mine_governor" in caps:
                gov.append(n)
                continue
        other.append(n)
    return gov + other
