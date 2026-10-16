#!/usr/bin/env python3
"""Regression tests for Redis redaction, dashboard auth helper, delivery semantics."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RedisRedactionTests(unittest.TestCase):
    def test_redact_password_user(self):
        from dashboard.comms_security import redact_redis

        raw = "redis://alice:s3cret@10.0.0.5:6379/0"
        out = redact_redis(raw)
        self.assertNotIn("s3cret", out)
        self.assertNotIn("alice", out)
        self.assertIn("10.0.0.5:6379/0", out)
        self.assertIn("***@", out)

    def test_redact_password_only(self):
        from dashboard.comms_security import redact_redis

        raw = "redis://:p@ssw0rd@192.168.1.10:6379/1"
        out = redact_redis(raw)
        self.assertNotIn("p@ssw0rd", out)
        self.assertIn("192.168.1.10:6379/1", out)

    def test_no_credentials_unchanged(self):
        from dashboard.comms_security import redact_redis

        raw = "redis://127.0.0.1:6379/0"
        self.assertEqual(redact_redis(raw), raw)

    def test_empty(self):
        from dashboard.comms_security import redact_redis

        self.assertEqual(redact_redis(""), "")


class DashboardAuthHelperTests(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get("AURORA_DASHBOARD_API_KEY")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("AURORA_DASHBOARD_API_KEY", None)
        else:
            os.environ["AURORA_DASHBOARD_API_KEY"] = self._prev

    def test_open_when_key_unset(self):
        os.environ.pop("AURORA_DASHBOARD_API_KEY", None)
        from dashboard.comms_security import check_dashboard_auth

        ok, detail = check_dashboard_auth({})
        self.assertTrue(ok)
        self.assertIsNone(detail)

    def test_reject_missing_key(self):
        os.environ["AURORA_DASHBOARD_API_KEY"] = "test-secret-key"
        from dashboard.comms_security import check_dashboard_auth

        ok, detail = check_dashboard_auth({})
        self.assertFalse(ok)
        self.assertIn("X-API-Key", detail or "")

    def test_accept_x_api_key(self):
        os.environ["AURORA_DASHBOARD_API_KEY"] = "test-secret-key"
        from dashboard.comms_security import check_dashboard_auth

        ok, _ = check_dashboard_auth({"X-API-Key": "test-secret-key"})
        self.assertTrue(ok)

    def test_accept_bearer(self):
        os.environ["AURORA_DASHBOARD_API_KEY"] = "test-secret-key"
        from dashboard.comms_security import check_dashboard_auth

        ok, _ = check_dashboard_auth({"Authorization": "Bearer test-secret-key"})
        self.assertTrue(ok)

    def test_reject_wrong_key(self):
        os.environ["AURORA_DASHBOARD_API_KEY"] = "test-secret-key"
        from dashboard.comms_security import check_dashboard_auth

        ok, _ = check_dashboard_auth({"X-API-Key": "wrong"})
        self.assertFalse(ok)


class SoloComposeRedisSafetyTests(unittest.TestCase):
    def test_solo_binds_loopback(self):
        text = (ROOT / "docker-compose.solo.yml").read_text()
        self.assertIn('"127.0.0.1"', text)
        self.assertNotIn('"0.0.0.0"', text)
        self.assertIn("protected-mode", text)
        after = text.split("protected-mode")[1][:40].lower()
        self.assertNotIn('"no"', after)

    def test_mesh_requires_password(self):
        text = (ROOT / "docker-compose.mesh.yml").read_text()
        self.assertIn("REDIS_PASSWORD", text)
        self.assertIn("requirepass", text)
        self.assertIn("protected-mode yes", text)

    def test_control_plane_no_host_port(self):
        text = (ROOT / "docker-compose.yml").read_text()
        redis_section = text.split("scheduler:")[0]
        self.assertNotIn('"6379:6379"', redis_section)


class RelayStillDisabledTests(unittest.TestCase):
    def test_relay_flag(self):
        from comms.routing.egress import RELAY_IMPLEMENTED, EgressGateway, EgressConfig

        self.assertFalse(RELAY_IMPLEMENTED)
        gw = EgressGateway(EgressConfig(enabled=True, port=9999, bind_host="127.0.0.1"))
        self.assertFalse(gw.start_listener())
        self.assertEqual(gw.last_error, "relay_not_implemented")


if __name__ == "__main__":
    unittest.main()
