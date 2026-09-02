#!/usr/bin/env python3
"""Possession is temporally addressable. Peer claims are not historical truth."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mods.asset_fabric.fabric import AssetFabric  # noqa: E402
from mods.asset_fabric.history import COMPLETE, POSSESSION_VERIFIED, PUBLISHED  # noqa: E402
from mods.asset_fabric.manifest_model import AssetManifest  # noqa: E402
from mods.btc_anchor.chain import SimulatedBitcoinChain  # noqa: E402
from tests.memory_comms import MemoryBus, MemoryComms  # noqa: E402


class TemporalPossessionTests(unittest.TestCase):
    def setUp(self):
        self.bus = MemoryBus()
        self.chain = SimulatedBitcoinChain(start_height=900000)
        self.fabric = AssetFabric(
            MemoryComms("holder", self.bus),
            chain=self.chain,
            confirmation_depth=1,
            btc_enabled=True,
        )

    def test_possession_carries_epoch_fields(self):
        m = AssetManifest.from_payload(b"possessed-bytes", piece_size=32)
        self.fabric.register_manifest(m)
        ev = self.fabric.possession(m.asset_id)
        self.assertEqual(ev["asset_id"], m.asset_id)
        self.assertEqual(ev["manifest_hash"], m.identity_hash())
        self.assertEqual(ev["peer_id"], "holder")
        self.assertIn("possession_state", ev)
        self.assertIn("verified_pieces", ev)
        self.assertIn("total_pieces", ev)
        self.assertIn("epoch", ev)
        self.assertIn("anchor_id", ev)

    def test_peer_claim_cannot_fabricate_historical_epoch(self):
        m = AssetManifest.from_payload(b"no-fake-history", piece_size=32)
        self.fabric.register_manifest(m)
        fake = {
            "asset_id": m.asset_id,
            "manifest_hash": m.identity_hash(),
            "btc_height": 900000,
            "btc_block_hash": "ab" * 32,
            "epoch": 900000,
            "anchor_id": "forged",
            "confidence": "confirmed",
        }
        result = self.fabric.verify_anchor(m.asset_id, claimed=fake)
        self.assertFalse(result.get("accepted"))
        clock = self.fabric.get_clock(m.asset_id)
        self.assertIsNone(clock.epoch)
        self.assertEqual(clock.confidence, "none")

    def test_complete_is_not_creation_time(self):
        m = AssetManifest.from_payload(b"completed-later", piece_size=32)
        self.fabric.register_manifest(m)
        self.fabric.anchor_asset(m.asset_id)
        self.chain.mine()
        self.chain.mine()
        self.fabric._clock_adapter()._get_anchor().apply_chain_progress()
        clock = self.fabric.get_clock(m.asset_id)
        payload = {
            "asset_id": m.asset_id,
            "manifest_hash": m.identity_hash(),
            "peer_id": "holder",
            "possession_proof": {"complete": True},
            "epoch": clock.epoch,
            "btc_anchor": clock.anchor_id,
        }
        accepted = self.fabric.ingest_complete_event(payload, verified=True)
        self.assertTrue(accepted["ok"])
        # Completion records reconstruction, not genesis.
        events = self.fabric.get_history(m.asset_id)
        types = [e["event_type"] for e in events]
        self.assertIn(PUBLISHED, types)
        self.assertIn(COMPLETE, types)
        complete = [e for e in events if e["event_type"] == COMPLETE][0]
        self.assertEqual(complete["epoch"], clock.epoch)
        published = [e for e in events if e["event_type"] == PUBLISHED][0]
        self.assertIsNone(published["epoch"])

    def test_peer_emitted_complete_is_not_authoritative(self):
        m = AssetManifest.from_payload(b"liar-complete", piece_size=32)
        self.fabric.register_manifest(m)
        payload = {
            "asset_id": m.asset_id,
            "manifest_hash": m.identity_hash(),
            "peer_id": "evil",
            "possession_proof": {"complete": True},
            "epoch": 900000,
            "btc_anchor": "nope",
        }
        rejected = self.fabric.ingest_complete_event(payload, verified=False)
        self.assertFalse(rejected.get("accepted"))
        types = [e["event_type"] for e in self.fabric.get_history(m.asset_id)]
        self.assertNotIn(COMPLETE, types)

    def test_only_verified_possession_is_recorded(self):
        m = AssetManifest.from_payload(b"verified-only", piece_size=32)
        self.fabric.register_manifest(m)
        # Local register_manifest does record verified possession for the publisher
        # because the publisher has the bytes. A remote claim does not.
        types = [e["event_type"] for e in self.fabric.get_history(m.asset_id)]
        self.assertIn(PUBLISHED, types)
        # Remote peer claim:
        other = AssetFabric(MemoryComms("stranger", self.bus), chain=self.chain, btc_enabled=True)
        claim_result = other.ingest_complete_event(
            {
                "asset_id": m.asset_id,
                "peer_id": "stranger",
                "possession_proof": {"complete": True},
                "epoch": 1,
            },
            verified=False,
        )
        self.assertFalse(claim_result.get("accepted"))


if __name__ == "__main__":
    unittest.main()
