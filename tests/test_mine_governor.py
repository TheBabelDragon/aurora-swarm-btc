#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mods.mine_governor.control import plan, scale_threads
from mods.mine_governor.history import last, recent, record
from mods.mine_governor.hooks.on_node_select import on_node_select


class PlanTests(unittest.TestCase):
    def test_pause_is_stop(self):
        self.assertEqual(plan("pause")["apply"], "stop")

    def test_resume_is_start(self):
        self.assertEqual(plan("resume")["apply"], "start")

    def test_restart_alias(self):
        self.assertEqual(plan("restart_miner")["apply"], "restart")

    def test_scale_threads(self):
        self.assertEqual(scale_threads(8, 0.5, None, 8), 4)
        p = plan("adjust_intensity", current_threads=8, cpus=8, factor=0.5)
        self.assertEqual(p["threads"], 4)

    def test_unknown(self):
        self.assertFalse(plan("launch_nukes")["ok"])


class HistoryTests(unittest.TestCase):
    def test_record_roundtrip(self):
        record("pause", {"ok": True, "applied": True, "apply": "stop"})
        self.assertEqual(last()["action"], "pause")
        self.assertTrue(any(i["action"] == "pause" for i in recent(10)))


class SelectTests(unittest.TestCase):
    def test_mining_prefers_governor(self):
        nodes = [
            {"node_id": "a", "capabilities": []},
            {"node_id": "b", "capabilities": ["mine_governor"]},
        ]
        out = on_node_select(nodes, task_type="mining")
        self.assertEqual(out[0]["node_id"], "b")

    def test_other_task_unchanged(self):
        nodes = [{"node_id": "a"}, {"node_id": "b", "capabilities": ["mine_governor"]}]
        self.assertEqual(on_node_select(nodes, task_type="chat")[0]["node_id"], "a")


if __name__ == "__main__":
    unittest.main()
