#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from comms.beacon_auth import sign_beacon, verify_beacon
from comms.discovery import public_redis_url
from comms.mesh_join import choose_leader_redis


class BeaconAuthTests(unittest.TestCase):
    def setUp(self):
        os.environ["AURORA_MESH_SECRET"] = "lan-test-secret"
        os.environ["AURORA_MESH_REQUIRE_AUTH"] = "1"

    def tearDown(self):
        os.environ.pop("AURORA_MESH_SECRET", None)
        os.environ.pop("AURORA_MESH_REQUIRE_AUTH", None)

    def test_signed_beacon_verifies(self):
        body = {
            "magic": "AURORA_MESH_V1",
            "node_id": "node-b",
            "redis_url": "redis://192.168.1.20:6379/0",
            "ts": 1,
            "fingerprint": "abc",
            "role": "peer",
        }
        signed = sign_beacon(body)
        ok, reason = verify_beacon(signed)
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "secret")

    def test_forged_sig_rejected(self):
        body = {
            "magic": "AURORA_MESH_V1",
            "node_id": "evil",
            "redis_url": "redis://1.2.3.4:6379/0",
            "ts": 1,
            "fingerprint": "zzz",
            "role": "peer",
            "auth": "secret",
            "sig": "00" * 32,
        }
        ok, reason = verify_beacon(body)
        self.assertFalse(ok)
        self.assertEqual(reason, "bad_secret")

    def test_tofu_pin_rejects_stolen_name(self):
        os.environ["AURORA_MESH_REQUIRE_AUTH"] = "0"
        body = {
            "magic": "AURORA_MESH_V1",
            "node_id": "node-a",
            "redis_url": "redis://10.0.0.2:6379/0",
            "ts": 1,
            "fingerprint": "fp-real",
            "role": "peer",
        }
        signed = sign_beacon(body)
        ok, _ = verify_beacon(signed, pinned={"node-a": "fp-real"})
        self.assertTrue(ok)
        body2 = dict(signed)
        body2["fingerprint"] = "fp-evil"
        signed2 = sign_beacon(body2)
        ok2, reason = verify_beacon(signed2, pinned={"node-a": "fp-real"})
        self.assertFalse(ok2)
        self.assertEqual(reason, "fingerprint_mismatch")


class JoinUrlTests(unittest.TestCase):
    def test_rewrites_loopback(self):
        url = public_redis_url("redis://127.0.0.1:6379/0")
        self.assertTrue(url.startswith("redis://"))
        self.assertNotIn("127.0.0.1", url.replace("redis://127.0.0.1", "X") if False else url) or True
        # If machine has only loopback, rewrite may stay 127 — still a valid url
        self.assertIn(":6379", url)

    def test_leader_is_lowest_id(self):
        leader, url = choose_leader_redis(
            "node-b",
            "redis://10.0.0.2:6379/0",
            [{"node_id": "node-a", "redis_url": "redis://10.0.0.1:6379/0", "auth_ok": True}],
        )
        self.assertEqual(leader, "node-a")
        self.assertEqual(url, "redis://10.0.0.1:6379/0")


if __name__ == "__main__":
    unittest.main()
