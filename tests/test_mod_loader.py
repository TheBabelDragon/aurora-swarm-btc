#!/usr/bin/env python3
"""Loader + hook-registry smoke tests. No Redis."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mods.loader import load_mods  # noqa: E402
from scheduler.hook_registry import HookRegistry  # noqa: E402


class LoaderTests(unittest.TestCase):
    def test_loader_finds_core_mods(self):
        loaded = load_mods(str(ROOT / "mods"))
        self.assertIn("metafield_bridge", loaded)
        self.assertIn("thermal_aware_scheduler", loaded)
        self.assertIn("gpu_utilization_balancer", loaded)
        self.assertIn("torrent_protocol", loaded)
        self.assertTrue(loaded["metafield_bridge"].get("enabled"))


class HookChainTests(unittest.TestCase):
    def test_hooks_compose_lists(self):
        reg = HookRegistry()

        def drop_hot(nodes, task=None):
            return [n for n in nodes if n.get("thermal", 0) < 80]

        def prefer_named(nodes, task=None):
            return sorted(nodes, key=lambda n: 0 if n.get("id") == "cool" else 1)

        reg.register("on_node_select", drop_hot)
        reg.register("on_node_select", prefer_named)
        out = reg.run(
            "on_node_select",
            [
                {"id": "hot", "thermal": 90},
                {"id": "warm", "thermal": 40},
                {"id": "cool", "thermal": 30},
            ],
            {},
        )
        self.assertEqual([n["id"] for n in out], ["cool", "warm"])


if __name__ == "__main__":
    unittest.main()
