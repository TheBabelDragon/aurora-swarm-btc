"""metafield_bridge mod entrypoint.

Safe to import without Redis, torch, or a live MetaField process.
"""

from __future__ import annotations

import argparse
import logging
import time
from typing import Any, Dict, List

from mods.metafield_bridge.bridge import snapshot_from_stats, load_stats, tick

logger = logging.getLogger("aurora.mods.metafield_bridge")


def on_sensing_tick(context: Any = None) -> Dict[str, Any]:
    snap = tick()
    logger.info(
        "metafield health=%s live=%s traj=%s published=%s",
        snap.get("health"),
        snap.get("live"),
        snap.get("traj"),
        (snap.get("publish") or {}).get("published"),
    )
    return snap


def on_node_select(nodes: List[Dict[str, Any]], task: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """Prefer nodes that already host a live MetaField body for field tasks."""
    if not nodes:
        return nodes
    task = task or {}
    kind = str(task.get("type") or task.get("kind") or "").lower()
    fieldish = kind in {"metafield", "lattice", "field", "hmc"} or bool(task.get("prefer_metafield"))
    if not fieldish:
        return nodes

    snap = snapshot_from_stats(load_stats())
    live = bool(snap.get("live"))

    def score(node: Dict[str, Any]) -> tuple:
        caps = node.get("capabilities") or node.get("caps") or []
        has_body = "metafield" in caps or node.get("metafield_live") or live
        return (0 if has_body else 1, node.get("id", ""))

    return sorted(nodes, key=score)


def register() -> None:
    try:
        from scheduler.hook_registry import registry

        registry.register("on_sensing_tick", on_sensing_tick)
        registry.register("on_node_select", on_node_select)
    except Exception as exc:
        logger.warning("hook registry unavailable (%s); CLI still works", exc)
    logger.info("metafield_bridge registered")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish MetaField stats onto the Aurora mesh")
    parser.add_argument("--once", action="store_true", help="single tick then exit")
    parser.add_argument("--watch", action="store_true", help="loop until Ctrl+C")
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    snap = on_sensing_tick()
    print(snap)
    if args.watch and not args.once:
        while True:
            time.sleep(max(1.0, args.interval))
            print(on_sensing_tick())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
