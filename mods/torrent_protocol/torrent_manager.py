"""
Aurora Swarm Torrent Manager
----------------------------
Lightweight, mesh-native piece distribution inspired by BitTorrent.

No external BitTorrent libraries required.
Uses the existing CommsLayer (Redis mesh) for announce, piece requests,
and piece data transfer.

Typical flow:
1. A node creates a torrent from a local file → gets an infohash
2. It announces the torrent (metadata + piece hashes) to the mesh
3. Other nodes with the "torrent" capability can request missing pieces
4. Pieces are transferred peer-to-peer over the mesh
5. Once complete, the receiver can become a seeder too

This is ideal for distributing large assets (AI models, GPU kernels,
config packs, etc.) without hammering a central registry or S3.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from comms.layer import CommsLayer, SwarmMessage

logger = logging.getLogger("aurora.torrent")

# Default piece size (256 KiB) — good balance for mesh latency vs overhead
DEFAULT_PIECE_SIZE = 256 * 1024


@dataclass
class TorrentMeta:
    infohash: str
    name: str
    size: int
    piece_size: int
    piece_hashes: List[str]          # list of hex SHA-256 of each piece
    created_by: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "infohash": self.infohash,
            "name": self.name,
            "size": self.size,
            "piece_size": self.piece_size,
            "piece_hashes": self.piece_hashes,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "num_pieces": len(self.piece_hashes),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TorrentMeta":
        return cls(
            infohash=d["infohash"],
            name=d["name"],
            size=d["size"],
            piece_size=d["piece_size"],
            piece_hashes=d["piece_hashes"],
            created_by=d["created_by"],
            created_at=d.get("created_at", time.time()),
        )


class TorrentManager:
    """
    Manages torrents for a single Aurora node.

    Register this node with capability "torrent" so others can discover it.
    """

    def __init__(self, comms: CommsLayer, storage_dir: Optional[str] = None):
        self.comms = comms
        self.node_id = comms.node_id
        self.storage_dir = Path(storage_dir or os.getenv("AURORA_TORRENT_DIR", "/tmp/aurora_torrents"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # infohash → TorrentMeta
        self.torrents: Dict[str, TorrentMeta] = {}

        # infohash → set of piece indices we currently have
        self.have: Dict[str, Set[int]] = {}

        # infohash → {piece_index → raw bytes} for in-progress downloads
        self.pieces: Dict[str, Dict[int, bytes]] = {}

        # Simple callbacks for completion / progress
        self.on_complete: Optional[Callable[[str, Path], None]] = None
        self.on_progress: Optional[Callable[[str, int, int], None]] = None  # infohash, have, total

        # Wire up mesh handlers
        self.comms.subscribe("torrent.announce", self._on_announce)
        self.comms.subscribe("torrent.piece_request", self._on_piece_request)
        self.comms.subscribe("torrent.piece_data", self._on_piece_data)

        logger.info(f"TorrentManager ready on node={self.node_id} storage={self.storage_dir}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_torrent(
        self,
        file_path: str | Path,
        name: Optional[str] = None,
        piece_size: int = DEFAULT_PIECE_SIZE,
    ) -> TorrentMeta:
        """
        Split a local file into pieces, compute hashes, and return metadata.
        Does NOT announce yet — call announce() afterwards.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Cannot create torrent: {path} not found")

        data = path.read_bytes()
        size = len(data)
        piece_hashes: List[str] = []
        pieces: Dict[int, bytes] = {}

        for i in range(0, size, piece_size):
            chunk = data[i : i + piece_size]
            h = hashlib.sha256(chunk).hexdigest()
            piece_hashes.append(h)
            pieces[len(piece_hashes) - 1] = chunk

        # Infohash = SHA-256 of the ordered piece hashes (simple deterministic ID)
        infohash = hashlib.sha256("".join(piece_hashes).encode()).hexdigest()[:40]

        meta = TorrentMeta(
            infohash=infohash,
            name=name or path.name,
            size=size,
            piece_size=piece_size,
            piece_hashes=piece_hashes,
            created_by=self.node_id,
        )

        self.torrents[infohash] = meta
        self.have[infohash] = set(range(len(piece_hashes)))
        self.pieces[infohash] = pieces

        # Persist the complete file under storage for easy seeding
        dest = self.storage_dir / f"{infohash}_{meta.name}"
        dest.write_bytes(data)

        logger.info(f"Created torrent {infohash[:12]}… name={meta.name} pieces={len(piece_hashes)}")
        return meta

    def announce(self, infohash: str):
        """Broadcast torrent metadata to the mesh so other nodes can discover it."""
        meta = self.torrents.get(infohash)
        if not meta:
            raise KeyError(f"Unknown torrent {infohash}")

        msg = SwarmMessage(
            type="torrent.announce",
            payload=meta.to_dict(),
            source=self.node_id,
        )
        self.comms.publish_message("torrent.announce", msg)
        # Also store in Redis for late joiners
        self.comms.set_state(f"torrent:{infohash}", meta.to_dict(), expire=3600)
        logger.info(f"Announced torrent {infohash[:12]}… to mesh")

    def start_download(self, infohash: str, meta: Optional[TorrentMeta] = None):
        """
        Begin downloading a torrent. If meta is not provided we look it up
        from the mesh state.
        """
        if infohash in self.have and len(self.have[infohash]) == len(
            self.torrents.get(infohash, meta or TorrentMeta("", "", 0, 0, [], "")).piece_hashes
        ):
            logger.info(f"Already complete: {infohash[:12]}")
            return

        if meta is None:
            raw = self.comms.get_state(f"torrent:{infohash}")
            if not raw:
                raise ValueError(f"No metadata found for {infohash} — has it been announced?")
            meta = TorrentMeta.from_dict(raw)

        self.torrents[infohash] = meta
        self.have.setdefault(infohash, set())
        self.pieces.setdefault(infohash, {})

        missing = set(range(len(meta.piece_hashes))) - self.have[infohash]
        logger.info(f"Starting download {infohash[:12]}… missing {len(missing)}/{len(meta.piece_hashes)} pieces")

        # Request pieces from any available torrent peers
        for idx in list(missing)[:16]:  # limit burst
            self._request_piece(infohash, idx)

    def get_progress(self, infohash: str) -> Dict[str, Any]:
        meta = self.torrents.get(infohash)
        if not meta:
            return {"error": "unknown torrent"}
        have = len(self.have.get(infohash, set()))
        total = len(meta.piece_hashes)
        return {
            "infohash": infohash,
            "name": meta.name,
            "have": have,
            "total": total,
            "percent": round(100.0 * have / total, 1) if total else 0.0,
            "complete": have == total,
        }

    def list_torrents(self) -> List[Dict[str, Any]]:
        return [self.get_progress(h) for h in self.torrents]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request_piece(self, infohash: str, piece_index: int):
        msg = SwarmMessage(
            type="torrent.piece_request",
            payload={"infohash": infohash, "piece_index": piece_index},
            source=self.node_id,
        )
        # Broadcast request — any seeder that has the piece can respond
        self.comms.publish_message("torrent.piece_request", msg)

    def _on_announce(self, msg: SwarmMessage):
        if msg.source == self.node_id:
            return
        payload = msg.payload
        infohash = payload.get("infohash")
        if not infohash:
            return
        # Cache metadata for later
        self.comms.set_state(f"torrent:{infohash}", payload, expire=3600)
        logger.debug(f"Cached announce for {infohash[:12]}… from {msg.source}")

    def _on_piece_request(self, msg: SwarmMessage):
        if msg.source == self.node_id:
            return
        infohash = msg.payload.get("infohash")
        idx = msg.payload.get("piece_index")
        if infohash is None or idx is None:
            return

        if infohash in self.have and idx in self.have[infohash]:
            piece_data = self.pieces.get(infohash, {}).get(idx)
            if piece_data is None:
                # Try to load from disk if we seeded earlier
                meta = self.torrents.get(infohash)
                if meta:
                    path = self.storage_dir / f"{infohash}_{meta.name}"
                    if path.exists():
                        data = path.read_bytes()
                        start = idx * meta.piece_size
                        piece_data = data[start : start + meta.piece_size]

            if piece_data:
                reply = SwarmMessage(
                    type="torrent.piece_data",
                    payload={
                        "infohash": infohash,
                        "piece_index": idx,
                        "data": piece_data.hex(),  # hex for JSON safety
                        "hash": hashlib.sha256(piece_data).hexdigest(),
                    },
                    source=self.node_id,
                    target=msg.source,
                )
                self.comms.publish_message("torrent.piece_data", reply)
                logger.debug(f"Served piece {idx} of {infohash[:12]}… to {msg.source}")

    def _on_piece_data(self, msg: SwarmMessage):
        if msg.source == self.node_id:
            return
        # Only accept if targeted at us or broadcast
        if msg.target and msg.target != self.node_id:
            return

        infohash = msg.payload.get("infohash")
        idx = msg.payload.get("piece_index")
        data_hex = msg.payload.get("data")
        expected_hash = msg.payload.get("hash")

        if not all([infohash, idx is not None, data_hex, expected_hash]):
            return

        try:
            data = bytes.fromhex(data_hex)
        except ValueError:
            logger.warning("Invalid piece data hex")
            return

        if hashlib.sha256(data).hexdigest() != expected_hash:
            logger.warning(f"Piece hash mismatch for {infohash[:12]} piece {idx}")
            return

        meta = self.torrents.get(infohash)
        if not meta:
            return

        if idx in self.have.get(infohash, set()):
            return  # already have it

        # Accept the piece
        self.pieces.setdefault(infohash, {})[idx] = data
        self.have.setdefault(infohash, set()).add(idx)

        have_count = len(self.have[infohash])
        total = len(meta.piece_hashes)

        if self.on_progress:
            self.on_progress(infohash, have_count, total)

        logger.debug(f"Got piece {idx} of {infohash[:12]}… ({have_count}/{total})")

        # Check completion
        if have_count == total:
            self._assemble_and_finish(infohash)

        # Opportunistically request more missing pieces
        missing = set(range(total)) - self.have[infohash]
        for next_idx in list(missing)[:4]:
            self._request_piece(infohash, next_idx)

    def _assemble_and_finish(self, infohash: str):
        meta = self.torrents[infohash]
        pieces = self.pieces[infohash]
        ordered = b"".join(pieces[i] for i in range(len(meta.piece_hashes)))

        if len(ordered) != meta.size:
            logger.error(f"Size mismatch after assembly for {infohash}")
            return

        dest = self.storage_dir / f"{infohash}_{meta.name}"
        dest.write_bytes(ordered)
        logger.info(f"Torrent complete → {dest}")

        if self.on_complete:
            self.on_complete(infohash, dest)


# Convenience helper for workers that want to register the capability
def register_torrent_capability(comms: CommsLayer, extra_caps: Optional[List[str]] = None):
    caps = ["torrent"] + (extra_caps or [])
    comms.register_node(
        node_type="worker",  # or whatever the node actually is
        capabilities=caps,
        metadata={"torrent_version": "0.1.0"},
    )
    logger.info(f"Registered torrent capability on {comms.node_id}")
