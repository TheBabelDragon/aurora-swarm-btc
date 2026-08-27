#!/usr/bin/env python3
"""Smoke tests for mods/metafield_bridge. No Redis, no torch."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mods.metafield_bridge.bridge import (  # noqa: E402
    load_stats,
    publish_snapshot,
    snapshot_from_stats,
    stats_path,
)
from mods.metafield_bridge.entrypoint import on_node_select  # noqa: E402


class StatsPathTests(unittest.TestCase):
    def test_explicit_env_wins(self):
        os.environ["METAFIELD_STATS_PATH"] = "/tmp/custom-mf-stats.json"
        try:
            self.assertEqual(stats_path(), Path("/tmp/custom-mf-stats.json"))
        finally:
            os.environ.pop("METAFIELD_STATS_PATH", None)


class SnapshotTests(unittest.TestCase):
    def test_missing_file_is_not_live(self):
        snap = snapshot_from_stats(None)
        self.assertFalse(snap["live"])
        self.assertEqual(snap["health"], "no_export")

    def test_live_export_roundtrip(self):
        payload = {
            "schema_version": 5,
            "health": "ok",
            "live": True,
            "traj": 12,
            "hmc": {"acceptance_rate": 0.82, "recent_abs_dh": 0.04},
            "geometry": {"train_loss": 1.2e-3},
            "attractors": {"num_attractors": 3, "total_energy": 11.0},
            "memory": {"size": 8, "soft_capacity": 64},
            "aurora": {"mode": "scale_up"},
        }
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "stats.json"
            p.write_text(json.dumps(payload))
            os.environ["METAFIELD_STATS_PATH"] = str(p)
            try:
                data = load_stats()
                snap = snapshot_from_stats(data)
            finally:
                os.environ.pop("METAFIELD_STATS_PATH", None)
        self.assertTrue(snap["live"])
        self.assertEqual(snap["traj"], 12)
        self.assertAlmostEqual(snap["hmc"]["acceptance_rate"], 0.82)
        self.assertEqual(snap["aurora_drive"], "scale_up")

    def test_publish_disabled_does_not_need_redis(self):
        os.environ["METAFIELD_BRIDGE_PUBLISH"] = "0"
        try:
            result = publish_snapshot({"health": "ok", "live": True, "timestamp": 0})
        finally:
            os.environ.pop("METAFIELD_BRIDGE_PUBLISH", None)
        self.assertFalse(result["published"])
        self.assertEqual(result["reason"], "disabled")


class NodeSelectTests(unittest.TestCase):
    def test_non_field_task_preserves_order(self):
        nodes = [{"id": "a"}, {"id": "b"}]
        out = on_node_select(nodes, {"type": "mine"})
        self.assertEqual([n["id"] for n in out], ["a", "b"])

    def test_field_task_prefers_metafield_cap(self):
        nodes = [
            {"id": "miner", "capabilities": ["gpu_mining"]},
            {"id": "body", "capabilities": ["metafield"]},
        ]
        out = on_node_select(nodes, {"type": "lattice"})
        self.assertEqual(out[0]["id"], "body")


if __name__ == "__main__":
    unittest.main()
