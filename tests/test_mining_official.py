#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mods.mining_engine.defaults import looks_like_btc_address, resolve_pool_url, sanitize_worker, stratum_user
from mods.mining_engine.mine_log import mine_log, tail


class RoutingTests(unittest.TestCase):
    def test_address_goes_solo_without_explicit_pool(self):
        os.environ.pop("POOL_URL", None)
        url = resolve_pool_url("bc1qdpqzuem4dkamt8ckcwaul7a2rhqju30xwn3f5g")
        self.assertIn("solo.stratum.braiins.com", url)

    def test_explicit_pool_wins(self):
        os.environ["POOL_URL"] = "stratum+tcp://example.com:3333"
        try:
            url = resolve_pool_url("bc1qdpqzuem4dkamt8ckcwaul7a2rhqju30xwn3f5g")
            self.assertIn("example.com", url)
        finally:
            os.environ.pop("POOL_URL", None)

    def test_user_format(self):
        self.assertTrue(looks_like_btc_address("bc1qdpqzuem4dkamt8ckcwaul7a2rhqju30xwn3f5g"))
        u = stratum_user("bc1qdpqzuem4dkamt8ckcwaul7a2rhqju30xwn3f5g", "node.bad name!")
        self.assertTrue(u.startswith("bc1q"))
        self.assertNotIn(" ", u.split(".", 1)[1])
        self.assertEqual(sanitize_worker("hello world"), "hello-world")


class LogTests(unittest.TestCase):
    def test_tail_roundtrip(self):
        fd, name = tempfile.mkstemp(prefix="aurora-mine-")
        os.close(fd)
        os.environ["AURORA_MINING_LOG"] = name
        try:
            mine_log("info", "connected demo")
            mine_log("ok", "share ACCEPTED")
            lines = tail(10)
            self.assertTrue(any("connected demo" in ln for ln in lines))
            self.assertTrue(any("ACCEPTED" in ln for ln in lines))
        finally:
            os.environ.pop("AURORA_MINING_LOG", None)
            Path(name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
