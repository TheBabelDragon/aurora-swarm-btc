#!/usr/bin/env python3
"""Post-merge live caller: mesh_send_to + resolve against fake mesh."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AURORA_DESTINATION_ROUTING_ENABLED", "1")

from comms.routing.service import DestinationRoutingService, init_routing_service, get_routing_service


class MeshSendToTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        nodes = {"worker-01": {"node_id": "worker-01", "node_type": "worker"}}

        def mesh_send(tid, payload):
            self.sent.append((tid, payload))
            return True

        self.svc = DestinationRoutingService(
            node_lookup=lambda n: nodes.get(n),
            mesh_send=mesh_send,
        )

    def test_mesh_send_to_known_node(self):
        r = self.svc.mesh_send_to("worker-01", {"text": "hi"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["result_kind"], "mesh_ack")
        self.assertEqual(r["transport"], "mesh")
        self.assertTrue(self.sent)
        self.assertEqual(self.sent[0][0], "worker-01")

    def test_mesh_send_rejects_ip_literal(self):
        r = self.svc.mesh_send_to("8.8.8.8", {"text": "no"})
        self.assertFalse(r["ok"])
        self.assertIn("mesh_send_requires", r["error"])

    def test_resolve_node(self):
        r = self.svc.resolve("worker-01")
        self.assertTrue(r.get("resolved"))
        self.assertEqual(r.get("reachable_hint"), "mesh_reachable")

    def test_no_mesh_transport(self):
        svc = DestinationRoutingService(
            node_lookup=lambda n: {"node_id": n} if n == "worker-01" else None,
            mesh_send=None,
        )
        r = svc.mesh_send_to("worker-01", {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "mesh_transport_unavailable")


class InitTests(unittest.TestCase):
    def test_init_disabled_by_default(self):
        os.environ["AURORA_DESTINATION_ROUTING_ENABLED"] = "0"
        # force reload config path via new service
        from comms.routing.config import load_routing_config

        cfg = load_routing_config()
        self.assertFalse(cfg.enabled)


if __name__ == "__main__":
    unittest.main()
