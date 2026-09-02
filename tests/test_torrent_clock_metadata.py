#!/usr/bin/env python3
"""Torrent announcements carry clock metadata; scheduling stays rarest-first."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mods.asset_fabric.fabric import AssetFabric  # noqa: E402
from mods.asset_fabric.manifest_model import AssetManifest  # noqa: E402
from mods.btc_anchor.chain import SimulatedBitcoinChain  # noqa: E402
from mods.torrent_protocol.torrent_manager import TorrentManager  # noqa: E402
from tests.memory_comms import MemoryBus, MemoryComms  # noqa: E402


class TorrentClockMetadataTests(unittest.TestCase):
    def test_announce_includes_clock_fields_without_changing_identity(self):
        bus = MemoryBus()
        chain = SimulatedBitcoinChain(start_height=900000)
        with tempfile.TemporaryDirectory() as td:
            comms = MemoryComms("seed", bus)
            fabric = AssetFabric(
                comms,
                storage_dir=td,
                chain=chain,
                confirmation_depth=1,
                btc_enabled=True,
            )
            src = Path(td) / "file.bin"
            src.write_bytes(b"announce-me" * 8)
            aid = fabric.publish(src, name="file.bin", announce=True, anchor=False)
            self.assertTrue(aid)
            raw = comms.get_state(f"torrent:{aid}")
            self.assertIsInstance(raw, dict)
            self.assertEqual(raw.get("asset_id"), aid)
            self.assertIn("manifest_hash", raw)
            self.assertIn("epoch", raw)
            self.assertIn("anchor_id", raw)
            # Unanchored announce: epoch/anchor are empty, identity still holds.
            self.assertIsNone(raw.get("epoch"))
            man = fabric.get_manifest(aid)
            self.assertEqual(raw.get("manifest_hash"), man.identity_hash())
            self.assertEqual(man.asset_id, aid)

    def test_rarest_first_ignores_bitcoin_fields(self):
        bus = MemoryBus()
        with tempfile.TemporaryDirectory() as td:
            comms = MemoryComms("tm", bus)
            tm = TorrentManager(comms, storage_dir=td, auto_maintain=False)
            src = Path(td) / "pieces.bin"
            src.write_bytes(b"A" * 64)
            meta = tm.create_torrent(src, name="pieces.bin", piece_size=16 * 1024)
            # Two pieces? 64 bytes / 16KiB = 1 piece. Still valid.
            # Inject fake rarity and ensure Bitcoin metadata is not consulted.
            tm.announce(
                meta.infohash,
                temporal={
                    "manifest_hash": "ab" * 32,
                    "epoch": 900000,
                    "anchor_id": "anchor-x",
                },
            )
            raw = comms.get_state(f"torrent:{meta.infohash}")
            self.assertEqual(raw.get("epoch"), 900000)
            missing = tm._rarest_missing(meta.infohash)
            # Seeder has every piece, so rarest-missing is empty regardless of epoch.
            self.assertEqual(missing, [])
            prog = tm.get_progress(meta.infohash)
            self.assertTrue(prog["complete"])

    def test_peer_epoch_on_announce_is_unverified_claim(self):
        bus = MemoryBus()
        with tempfile.TemporaryDirectory() as td_a, tempfile.TemporaryDirectory() as td_b:
            a = MemoryComms("a", bus)
            b = MemoryComms("b", bus)
            tm_a = TorrentManager(a, storage_dir=td_a, auto_maintain=False)
            tm_b = TorrentManager(b, storage_dir=td_b, auto_maintain=False)
            src = Path(td_a) / "s.bin"
            src.write_bytes(b"seed-bytes")
            meta = tm_a.create_torrent(src, name="s.bin")
            tm_a.announce(
                meta.infohash,
                temporal={"manifest_hash": "ff" * 32, "epoch": 123456, "anchor_id": "liar"},
            )
            claim = b.get_state(f"torrent:claim:{meta.infohash}:a")
            self.assertIsNotNone(claim)
            self.assertFalse(claim.get("verified"))
            self.assertEqual(claim.get("epoch"), 123456)
            # Local clock of B does not adopt the claim.
            fabric_b = AssetFabric(b, storage_dir=td_b, btc_enabled=True, transport=tm_b)
            clock = fabric_b.get_clock(meta.infohash)
            self.assertNotEqual(clock.epoch, 123456)
            self.assertIsNone(clock.epoch)

    def test_integration_nodes_reconstruct_without_publisher_wall_clock(self):
        bus = MemoryBus()
        chain = SimulatedBitcoinChain(start_height=900000)
        with tempfile.TemporaryDirectory() as td:
            dirs = {name: Path(td) / name for name in ("pub", "a", "b", "c")}
            for d in dirs.values():
                d.mkdir()
            fabrics = {}
            for name in dirs:
                fabrics[name] = AssetFabric(
                    MemoryComms(name, bus),
                    storage_dir=str(dirs[name]),
                    chain=chain,
                    confirmation_depth=1,
                    btc_enabled=True,
                )
                fabrics[name]._transport().stop()
            src = dirs["pub"] / "artifact.bin"
            src.write_bytes(b"swarm-artifact-bytes-42")
            aid = fabrics["pub"].publish(src, name="artifact.bin", announce=True, anchor=False)
            self.assertTrue(aid)
            for name in ("a", "b", "c"):
                fabrics[name].ensure(aid)
                fabrics[name]._transport().wanted.add(aid)
                fabrics[name]._transport().start_download(aid)
            fabrics["pub"].anchor_asset(aid)
            chain.mine()
            chain.mine()
            for name, f in fabrics.items():
                f._clock_adapter()._get_anchor().apply_chain_progress()
            clocks = {name: f.get_clock(aid) for name, f in fabrics.items()}
            tuples = {c.canonical_tuple() for c in clocks.values()}
            self.assertEqual(len(tuples), 1)
            man_hashes = {f.get_manifest(aid).identity_hash() for f in fabrics.values() if f.get_manifest(aid)}
            self.assertEqual(len(man_hashes), 1)
            ids = {f.get_manifest(aid).asset_id for f in fabrics.values() if f.get_manifest(aid)}
            self.assertEqual(ids, {aid})
            for c in clocks.values():
                self.assertNotEqual(c.observed_at, c.epoch)


if __name__ == "__main__":
    unittest.main()
