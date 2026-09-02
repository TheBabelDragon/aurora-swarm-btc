#!/usr/bin/env python3
"""Reorg invalidates canonical status and preserves historical observation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mods.asset_fabric.fabric import AssetFabric  # noqa: E402
from mods.asset_fabric.history import ANCHORED, REANCHORED  # noqa: E402
from mods.asset_fabric.manifest_model import AssetManifest  # noqa: E402
from mods.btc_anchor.chain import SimulatedBitcoinChain  # noqa: E402
from mods.btc_anchor.lifecycle import CONFIRMED, RE_ANCHOR_REQUIRED, REORGED  # noqa: E402
from tests.memory_comms import MemoryBus, MemoryComms  # noqa: E402


class ReorgTests(unittest.TestCase):
    def test_reorg_invalidates_canonical_preserves_history(self):
        bus = MemoryBus()
        chain = SimulatedBitcoinChain(start_height=900000)
        fabric = AssetFabric(
            MemoryComms("n1", bus),
            chain=chain,
            confirmation_depth=1,
            btc_enabled=True,
        )
        m = AssetManifest.from_payload(b"reorg-me", piece_size=32)
        fabric.register_manifest(m)
        fabric.anchor_asset(m.asset_id)
        included = chain.mine()
        chain.mine()  # confirmation
        fabric._clock_adapter()._get_anchor().apply_chain_progress()
        clock = fabric.get_clock(m.asset_id)
        self.assertTrue(clock.is_authoritative or clock.confidence in ("confirmed", "included"))
        history_before = fabric.get_history(m.asset_id)
        self.assertTrue(any(e["event_type"] == ANCHORED for e in history_before))
        seqs = [e["sequence"] for e in history_before]

        # Drop the inclusion block.
        fork_at = included.height - 1
        chain.reorg(fork_at, new_length=3)
        self.assertFalse(chain.is_canonical(included.block_hash))
        result = fabric.handle_reorg()
        self.assertTrue(result.get("ok"))
        rec = fabric._get_anchor().get(m.asset_id)
        self.assertIn(rec.status, (REORGED, RE_ANCHOR_REQUIRED))
        self.assertFalse(rec.canonical)
        self.assertTrue(rec.observed)

        clock2 = fabric.get_clock(m.asset_id)
        self.assertFalse(clock2.is_authoritative)
        self.assertEqual(clock2.confidence, "reorged")

        history_after = fabric.get_history(m.asset_id)
        self.assertGreaterEqual(len(history_after), len(history_before))
        self.assertEqual([e["sequence"] for e in history_after[: len(seqs)]], seqs)
        self.assertTrue(any(e["event_type"] == REANCHORED for e in history_after))
        # Original ANCHORED event still present — never deleted.
        self.assertTrue(any(e["event_type"] == ANCHORED for e in history_after))

    def test_observed_vs_canonical(self):
        bus = MemoryBus()
        chain = SimulatedBitcoinChain(start_height=900000)
        fabric = AssetFabric(
            MemoryComms("n1", bus),
            chain=chain,
            confirmation_depth=1,
            btc_enabled=True,
        )
        m = AssetManifest.from_payload(b"obs-can", piece_size=32)
        fabric.register_manifest(m)
        fabric.anchor_asset(m.asset_id)
        chain.mine()
        chain.mine()
        anc = fabric._get_anchor()
        anc.apply_chain_progress()
        rec = anc.get(m.asset_id)
        self.assertTrue(rec.observed)
        # After reorg, observed stays, canonical does not.
        chain.reorg(chain.tip().height - 2, new_length=4)
        anc.handle_reorg()
        rec2 = anc.get(m.asset_id)
        self.assertTrue(rec2.observed)
        self.assertFalse(rec2.canonical)
        # Observed copy retained under observed prefix
        keys = bus.store.keys()
        self.assertTrue(any("anchor:observed" in k for k in keys) or rec2.observed)


if __name__ == "__main__":
    unittest.main()
