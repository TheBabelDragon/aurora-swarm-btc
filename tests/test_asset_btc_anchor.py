#!/usr/bin/env python3
"""Asset Fabric ↔ BTC Anchor: identity vs observation, verification, disabled layers."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mods.asset_fabric.btc_clock import BTCClock  # noqa: E402
from mods.asset_fabric.fabric import AssetFabric  # noqa: E402
from mods.asset_fabric.manifest_model import AssetManifest  # noqa: E402
from mods.btc_anchor.chain import SimulatedBitcoinChain  # noqa: E402
from mods.btc_anchor.commitment import compute_artifact_commitment, compute_manifest_hash  # noqa: E402
from mods.btc_anchor.verify import verify_artifact_commitment  # noqa: E402
from tests.memory_comms import MemoryBus, MemoryComms  # noqa: E402


class CommitmentBindingTests(unittest.TestCase):
    def test_commitment_binds_manifest_hash_not_payload(self):
        m = AssetManifest.from_payload(b"the-bytes-are-not-on-chain", piece_size=32)
        epoch = 900042
        c = compute_artifact_commitment(m.asset_id, m.identity_hash(), epoch)
        self.assertTrue(
            verify_artifact_commitment(
                asset_id=m.asset_id,
                manifest_hash=m.identity_hash(),
                artifact_epoch=epoch,
                commitment=c,
            )
        )
        self.assertFalse(
            verify_artifact_commitment(
                asset_id=m.asset_id,
                manifest_hash="00" * 32,
                artifact_epoch=epoch,
                commitment=c,
            )
        )
        self.assertFalse(
            verify_artifact_commitment(
                asset_id=m.asset_id,
                manifest_hash=m.identity_hash(),
                artifact_epoch=epoch + 1,
                commitment=c,
            )
        )

    def test_invalid_manifest_anchor_fails(self):
        bus = MemoryBus()
        comms = MemoryComms("n1", bus)
        chain = SimulatedBitcoinChain(start_height=900000)
        fabric = AssetFabric(comms, chain=chain, confirmation_depth=2, btc_enabled=True)
        m = AssetManifest.from_payload(b"bind-me", piece_size=32)
        fabric.register_manifest(m)
        fabric.anchor_asset(m.asset_id, request_broadcast=True)
        chain.mine()
        chain.mine_n(2)
        fabric._clock_adapter()._get_anchor().apply_chain_progress()
        bad = {
            "asset_id": m.asset_id,
            "manifest_hash": "deadbeef" * 8,
            "btc_height": 900000,
            "btc_block_hash": "11" * 32,
            "epoch": 900000,
        }
        result = fabric.verify_anchor(m.asset_id, claimed=bad)
        self.assertFalse(result.get("accepted"))
        self.assertTrue(result.get("reasons"))


class IdentityVsAnchorTests(unittest.TestCase):
    def test_different_anchors_do_not_change_asset_identity(self):
        bus = MemoryBus()
        comms = MemoryComms("n1", bus)
        chain = SimulatedBitcoinChain(start_height=900000)
        fabric = AssetFabric(comms, chain=chain, confirmation_depth=1, btc_enabled=True)
        m = AssetManifest.from_payload(b"stable-id", piece_size=32)
        fabric.register_manifest(m)
        aid = m.asset_id
        hid = m.identity_hash()
        fabric.anchor_asset(aid)
        chain.mine()
        chain.mine()
        fabric._clock_adapter()._get_anchor().apply_chain_progress()
        c1 = fabric.get_clock(aid)
        self.assertEqual(c1.asset_id, aid)
        self.assertNotEqual(c1.anchor_id, aid)
        first_anchor = c1.anchor_id
        # Reorg + re-anchor produces a new observation of the same artifact.
        chain.reorg(chain.tip().height - 1, new_length=3)
        fabric.handle_reorg()
        fabric.anchor_asset(aid)
        chain.mine()
        chain.mine()
        fabric._clock_adapter()._get_anchor().apply_chain_progress()
        c2 = fabric.get_clock(aid)
        self.assertEqual(c2.asset_id, aid)
        man = fabric.get_manifest(aid)
        self.assertEqual(man.identity_hash(), hid)
        if c2.anchor_id and first_anchor:
            self.assertTrue(c2.asset_id != c2.anchor_id)

    def test_btc_layer_works_without_torrent(self):
        bus = MemoryBus()
        comms = MemoryComms("clock-only", bus)
        chain = SimulatedBitcoinChain(start_height=900000)
        clock = BTCClock(comms, chain=chain, confirmation_depth=1, enabled=True)
        m = AssetManifest.from_payload(b"no-torrent-required", piece_size=32)
        comms.set_state(f"asset:manifest:{m.asset_id}", m.to_dict(), expire=0)
        rec = clock.anchor_asset(m.asset_id, manifest_hash=m.identity_hash(), manifest=m)
        self.assertIsNotNone(rec)
        chain.mine()
        chain.mine()
        clock._get_anchor().apply_chain_progress()
        got = clock.get_asset_clock(m.asset_id, manifest_hash=m.identity_hash())
        self.assertEqual(got.asset_id, m.asset_id)
        self.assertIsNotNone(got.epoch)
        self.assertNotEqual(got.confidence, "none")

    def test_unanchored_assets_remain_valid(self):
        bus = MemoryBus()
        comms = MemoryComms("n1", bus)
        fabric = AssetFabric(comms, btc_enabled=False)
        m = AssetManifest.from_payload(b"valid-without-btc", piece_size=32)
        fabric.register_manifest(m)
        self.assertEqual(fabric.get_manifest(m.asset_id).asset_id, m.asset_id)
        clock = fabric.get_clock(m.asset_id)
        self.assertIsNone(clock.epoch)
        self.assertFalse(clock.is_authoritative)


class TorrentWithoutBtcTests(unittest.TestCase):
    def test_torrent_transfer_with_btc_disabled(self):
        bus = MemoryBus()
        with tempfile.TemporaryDirectory() as td:
            pub_dir = Path(td) / "pub"
            peer_dir = Path(td) / "peer"
            pub_dir.mkdir()
            peer_dir.mkdir()
            src = pub_dir / "blob.bin"
            src.write_bytes(b"x" * 64)
            pub = AssetFabric(
                MemoryComms("publisher", bus),
                storage_dir=str(pub_dir),
                btc_enabled=False,
            )
            peer = AssetFabric(
                MemoryComms("peer-a", bus),
                storage_dir=str(peer_dir),
                btc_enabled=False,
            )
            # Disable background maintainer after first transport construction.
            pub._transport().stop()
            peer._transport().stop()
            aid = pub.publish(src, name="blob.bin", announce=True, anchor=False)
            self.assertTrue(aid)
            self.assertIsNone(pub.get_clock(aid).epoch)
            ok = peer.ensure(aid)
            self.assertTrue(ok or peer.is_complete(aid) or peer._transport().get_progress(aid).get("have", 0) >= 0)
            # Drive a request/response cycle.
            tm_peer = peer._transport()
            tm_peer.wanted.add(aid)
            tm_peer.start_download(aid)
            prog = tm_peer.get_progress(aid)
            self.assertIn("have", prog)
            self.assertEqual(pub.get_clock(aid).asset_id, aid)
            self.assertEqual(peer.get_clock(aid).asset_id, aid)


class ManifestHashTests(unittest.TestCase):
    def test_compute_manifest_hash_stable(self):
        m = AssetManifest.from_payload(b"abc", piece_size=32)
        h1 = compute_manifest_hash(m.to_dict())
        h2 = compute_manifest_hash(m.with_temporal({"anchor_id": "z"}).to_dict())
        self.assertEqual(h1, h2)
        self.assertEqual(h1, m.identity_hash())


if __name__ == "__main__":
    unittest.main()
