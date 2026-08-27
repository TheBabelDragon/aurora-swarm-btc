#!/usr/bin/env python3
"""Hasher smoke — no pool required."""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class OfflineHasherTests(unittest.TestCase):
    def test_offline_start_produces_hashrate(self):
        os.environ["AURORA_MINE_OFFLINE"] = "1"
        os.environ["AURORA_CPU_THREADS"] = "2"
        from mods.mining_engine.stratum_cpu import StratumCpuMiner

        m = StratumCpuMiner("stratum+tcp://127.0.0.1:9", "x.x", threads=2)
        try:
            self.assertTrue(m.start())
            time.sleep(2.2)
            hs = m.get_hashrate_hs()
            self.assertGreater(hs, 0.0, f"expected hashes, got {hs}")
            self.assertTrue(m.running())
        finally:
            m.stop()
            os.environ.pop("AURORA_MINE_OFFLINE", None)


if __name__ == "__main__":
    unittest.main()
