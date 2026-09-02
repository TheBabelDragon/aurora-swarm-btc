#!/usr/bin/env python3
"""Canonical artifact clock: identity, epoch, wall-clock independence."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mods.asset_fabric.artifact_clock import (  # noqa: E402
    CONFIDENCE_CONFIRMED,
    CONFIDENCE_NONE,
    ArtifactClock,
)
from mods.asset_fabric.manifest_model import AssetManifest  # noqa: E402
from mods.btc_anchor.chain import SimulatedBitcoinChain  # noqa: E402
from mods.btc_anchor.commitment import compute_artifact_commitment  # noqa: E402
from mods.btc_anchor.records import AnchorRecord  # noqa: E402
from mods.btc_anchor.lifecycle import CONFIRMED  # noqa: E402


class IdentityTests(unittest.TestCase):
    def test_same_manifest_same_asset_identity(self):
        a = AssetManifest.from_payload(b"hello-swarm", name="a", piece_size=32)
        b = AssetManifest.from_payload(b"hello-swarm", name="b", piece_size=32)
        self.assertEqual(a.asset_id, b.asset_id)
        self.assertEqual(a.identity_hash(), b.identity_hash())

    def test_temporal_metadata_does_not_change_identity(self):
        m = AssetManifest.from_payload(b"payload-x", name="x", piece_size=32)
        hid = m.identity_hash()
        aid = m.asset_id
        m2 = m.with_temporal(
            {
                "clock_version": 1,
                "anchor_id": "abc",
                "btc_height": 900010,
                "btc_block_hash": "ff" * 32,
                "btc_work": "a",
                "anchored_at": 900010,
            }
        )
        self.assertEqual(m2.asset_id, aid)
        self.assertEqual(m2.identity_hash(), hid)
        self.assertNotEqual(m2.temporal, m.temporal)


class UnanchoredTests(unittest.TestCase):
    def test_unanchored_asset_has_no_epoch(self):
        m = AssetManifest.from_payload(b"lonely", piece_size=32)
        clock = ArtifactClock.unanchored(m.asset_id, m.identity_hash())
        self.assertIsNone(clock.epoch)
        self.assertIsNone(clock.btc_height)
        self.assertIsNone(clock.anchor_id)
        self.assertEqual(clock.confidence, CONFIDENCE_NONE)
        self.assertFalse(clock.is_authoritative)
        self.assertEqual(clock.asset_id, m.asset_id)

    def test_wall_clock_skew_does_not_alter_epoch(self):
        rec = {
            "asset_id": "aa" * 20,
            "manifest_hash": "bb" * 32,
            "status": CONFIRMED,
            "artifact_epoch": 900100,
            "btc_height": 900101,
            "btc_block_hash": "cc" * 32,
            "btc_work": "1f",
            "anchor_id": "dd" * 20,
            "created_at": 1.0,
            "included_at": 600,
            "canonical": True,
            "confirmations": 8,
            "confirmation_depth": 6,
            "commitment": "ee" * 32,
        }
        c1 = ArtifactClock.from_anchor_record(rec, manifest_hash=rec["manifest_hash"])
        rec2 = dict(rec)
        rec2["created_at"] = 999999.0  # observer skew on a field we do not use for epoch
        # included_at stays the same so derivation of observed_at is stable;
        # epoch must ignore created_at entirely.
        c2 = ArtifactClock.from_anchor_record(rec2, manifest_hash=rec["manifest_hash"])
        self.assertEqual(c1.epoch, c2.epoch)
        self.assertEqual(c1.btc_height, c2.btc_height)
        self.assertEqual(c1.canonical_tuple(), c2.canonical_tuple())
        self.assertNotEqual(c1.epoch, rec2["created_at"])


class DerivationTests(unittest.TestCase):
    def test_two_peers_derive_identical_clocks(self):
        chain = SimulatedBitcoinChain(start_height=900000)
        chain.mine()
        tip = chain.tip()
        rec = AnchorRecord(
            asset_id="aa" * 20,
            commitment=compute_artifact_commitment("aa" * 20, "bb" * 32, tip.height),
            status=CONFIRMED,
            manifest_hash="bb" * 32,
            artifact_epoch=tip.height,
            btc_height=tip.height,
            btc_block_hash=tip.block_hash,
            btc_work=tip.work,
            anchor_id="ff" * 20,
            included_at=tip.timestamp,
            created_at=tip.timestamp,
            confirmations=6,
            confirmation_depth=6,
            canonical=True,
        )
        c1 = ArtifactClock.from_anchor_record(rec, manifest_hash="bb" * 32)
        c2 = ArtifactClock.from_anchor_record(rec.to_dict(), manifest_hash="bb" * 32)
        self.assertEqual(c1, c2)
        self.assertEqual(c1.canonical_tuple(), c2.canonical_tuple())
        self.assertEqual(c1.confidence, CONFIDENCE_CONFIRMED)


if __name__ == "__main__":
    unittest.main()
