#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mods.mine_governor.control import plan, scale_threads


class PlanTests(unittest.TestCase):
    def test_pause_is_stop(self):
        p = plan("pause")
        self.assertTrue(p["ok"])
        self.assertEqual(p["apply"], "stop")

    def test_resume_is_start(self):
        p = plan("resume")
        self.assertEqual(p["apply"], "start")

    def test_restart_alias(self):
        p = plan("restart_miner")
        self.assertEqual(p["apply"], "restart")

    def test_scale_threads(self):
        self.assertEqual(scale_threads(8, 0.5, None, 8), 4)
        p = plan("adjust_intensity", current_threads=8, cpus=8, factor=0.5)
        self.assertEqual(p["apply"], "threads")
        self.assertEqual(p["threads"], 4)

    def test_unknown(self):
        p = plan("launch_nukes")
        self.assertFalse(p["ok"])


if __name__ == "__main__":
    unittest.main()
