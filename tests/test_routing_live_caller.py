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
        self.assertEqual(r["result_kind"], "send_accepted")
        self.assertTrue(r["send_attempted"])
        self.assertTrue(r["send_accepted"])
        self.assertFalse(r["recipient_acknowledged"])
        self.assertFalse(r["application_delivered"])
        self.assertEqual(r["transport"], "mesh")
        self.assertTrue(self.sent)
        self.assertEqual(self.sent[0][0], "worker-01")

    def test_mesh_send_rejects_ip_literal(self):
        r = self.svc.mesh_send_to("8.8.8.8", {"text": "no"})
        self.assertFalse(r["ok"])
        self.assertIn("mesh_send_requires", r["error"])
        self.assertFalse(r.get("send_attempted"))

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

    def test_mesh_send_false_is_failed(self):
        svc = DestinationRoutingService(
            node_lookup=lambda n: {"node_id": n} if n == "worker-01" else None,
            mesh_send=lambda tid, p: False,
        )
        r = svc.mesh_send_to("worker-01", {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["result_kind"], "failed")
        self.assertTrue(r["send_attempted"])
        self.assertFalse(r["send_accepted"])

    def test_mesh_send_exception_is_failed(self):
        def boom(tid, p):
            raise RuntimeError("transport down")

        svc = DestinationRoutingService(
            node_lookup=lambda n: {"node_id": n} if n == "worker-01" else None,
            mesh_send=boom,
        )
        r = svc.mesh_send_to("worker-01", {})
        self.assertFalse(r["ok"])
        self.assertEqual(r["result_kind"], "failed")
        self.assertTrue(r["send_attempted"])
        self.assertIn("transport down", r["error"])

    def test_mesh_send_dict_recipient_ack(self):
        def ack_send(tid, p):
            return {
                "ok": True,
                "send_accepted": True,
                "recipient_acknowledged": True,
            }

        svc = DestinationRoutingService(
            node_lookup=lambda n: {"node_id": n} if n == "worker-01" else None,
            mesh_send=ack_send,
        )
        r = svc.mesh_send_to("worker-01", {"text": "hi"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["result_kind"], "recipient_acknowledged")
        self.assertTrue(r["recipient_acknowledged"])
        self.assertFalse(r["application_delivered"])

    def test_mesh_send_dict_app_delivered(self):
        def deliv(tid, p):
            return {
                "send_accepted": True,
                "recipient_acknowledged": True,
                "application_delivered": True,
            }

        svc = DestinationRoutingService(
            node_lookup=lambda n: {"node_id": n} if n == "worker-01" else None,
            mesh_send=deliv,
        )
        r = svc.mesh_send_to("worker-01", {})
        self.assertTrue(r["ok"])
        self.assertEqual(r["result_kind"], "application_delivered")
        self.assertTrue(r["application_delivered"])


class InitTests(unittest.TestCase):
    def test_init_disabled_by_default(self):
        os.environ["AURORA_DESTINATION_ROUTING_ENABLED"] = "0"
        from comms.routing.config import load_routing_config

        cfg = load_routing_config()
        self.assertFalse(cfg.enabled)


if __name__ == "__main__":
    unittest.main()
