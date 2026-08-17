"""
Aurora Swarm Torrent Manager  v0.2.0
------------------------------------
Lightweight, mesh-native piece distribution inspired by BitTorrent.

New in 0.2.0:
- Rarest-first piece prioritization
- Parallel requests with back-pressure (max outstanding)
- Pending-request tracking + simple timeouts
- Listens for "asset.needed" mesh events (scheduler integration)

No external BitTorrent libraries required.
Uses the existing CommsLayer (Redis mesh) for all signalling and data.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from comms.layer import CommsLayer, SwarmMessage

logger = logging.getLogger("aurora.torrent")

DEFAULT_PIECE_SIZE = 256 * 1024
MAX_OUTSTANDING = 12          # back-pressure limit per torrent
REQUEST_TIMEOUT = 25.0        # seconds before we re-request a piece


@dataclass
class TorrentMeta:
    infohash: str
    name: str
    size: int
    piece_size: int
    piece_hashes: List[str]
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

    Register the node with capability "torrent" so others can discover it.
    """

    def __init__(
        self,
        comms: CommsLayer,
        storage_dir: Optional[str] = None,
        max_outstanding: int = MAX_OUTSTANDING,
    ):
        self.comms = comms
        self.node_id = comms.node_id
        self.storage_dir = Path(storage_dir or os.getenv("AURORA_TORRENT_DIR", "/tmp/aurora_torrents"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.max_outstanding = max_outstanding

        self.torrents: Dict[str, TorrentMeta] = {}
        self.have: Dict[str, Set[int]] = {}
        self.pieces: Dict[str, Dict[int, bytes]] = {}

        # Rarity tracking: infohash → {piece_index → known_count}
        self.rarity: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))

        # Outstanding requests: infohash → {piece_index → request_timestamp}
        self.pending: Dict[str, Dict[int, float]] = defaultdict(dict)

        self.on_complete: Optional[Callable[[str, Path], None]] = None
        self.on_progress: Optional[Callable[[str, int, int], None]] = None

        # Mesh handlers
        self.comms.subscribe("torrent.announce", self._on_announce)
        self.comms.subscribe("torrent.piece_request", self._on_piece_request)
        self.comms.subscribe("torrent.piece_data", self._on_piece_data)
        self.comms.subscribe("asset.needed", self._on_asset_needed)

        logger.info(
            f"TorrentManager v0.2.0 ready on node={self.node_id} "
            f"max_outstanding={self.max_outstanding}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_torrent(
        self,
        file_path: str | Path,
        name: Optional[str] = None,
        piece_size: int = DEFAULT_PIECE_SIZE,
    ) -> TorrentMeta:
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

        # Seeders know every piece is available at least once (themselves)
        for idx in range(len(piece_hashes)):
            self.rarity[infohash][idx] = 1

        dest = self.storage_dir / f"{infohash}_{meta.name}"
        dest.write_bytes(data)

        logger.info(f"Created torrent {infohash[:12]}… name={meta.name} pieces={len(piece_hashes)}")
        return meta

    def announce(self, infohash: str):
        meta = self.torrents.get(infohash)
        if not meta:
            raise KeyError(f"Unknown torrent {infohash}")

        msg = SwarmMessage(
            type="torrent.announce",
            payload=meta.to_dict(),
            source=self.node_id,
        )
        self.comms.publish_message("torrent.announce", msg)
        self.comms.set_state(f"torrent:{infohash}", meta.to_dict(), expire=3600)
        logger.info(f"Announced torrent {infohash[:12]}… to mesh")

    def start_download(self, infohash: str, meta: Optional[TorrentMeta] = None):
        if infohash in self.have:
            total = len(self.torrents.get(infohash, meta).piece_hashes) if (infohash in self.torrents or meta) else 0
            if total and len(self.have[infohash]) == total:
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
        logger.info(f"Starting download {infohash[:12]}… missing {len(missing)}/{len(meta.piece_hashes)}")

        self._fill_pipeline(infohash)

    def get_progress(self, infohash: str) -> Dict[str, Any]:
        meta = self.torrents.get(infohash)
        if not meta:
            return {"error": "unknown torrent"}
        have = len(self.have.get(infohash, set()))
        total = len(meta.piece_hashes)
        pending = len(self.pending.get(infohash, {}))
        return {
            "infohash": infohash,
            "name": meta.name,
            "have": have,
            "total": total,
            "pending": pending,
            "percent": round(100.0 * have / total, 1) if total else 0.0,
            "complete": have == total,
        }

    def list_torrents(self) -> List[Dict[str, Any]]:
        return [self.get_progress(h) for h in self.torrents]

    # ------------------------------------------------------------------
    # Rarest-first + back-pressure pipeline
    # ------------------------------------------------------------------

    def _rarest_missing(self, infohash: str) -> List[int]:
        """Return missing piece indices sorted rarest-first."""
        meta = self.torrents[infohash]
        have = self.have.get(infohash, set())
        pending = self.pending.get(infohash, {})
        rarity = self.rarity[infohash]

        candidates = []
        for idx in range(len(meta.piece_hashes)):
            if idx in have or idx in pending:
                continue
            # Unknown pieces are treated as very rare (count 0)
            count = rarity.get(idx, 0)
            candidates.append((count, idx))

        candidates.sort()  # ascending rarity, then by index
        return [idx for _, idx in candidates]

    def _fill_pipeline(self, infohash: str):
        """Issue new requests up to the outstanding limit, rarest-first."""
        self._expire_stale_requests(infohash)

        pending = self.pending[infohash]
        slots = self.max_outstanding - len(pending)
        if slots <= 0:
            return

        for idx in self._rarest_missing(infohash)[:slots]:
            self._request_piece(infohash, idx)

    def _expire_stale_requests(self, infohash: str):
        now = time.time()
        pending = self.pending[infohash]
        stale = [idx for idx, ts in pending.items() if now - ts > REQUEST_TIMEOUT]
        for idx in stale:
            del pending[idx]
            logger.debug(f"Timed out piece {idx} of {infohash[:12]}… — will re-request")

    def _request_piece(self, infohash: str, piece_index: int):
        self.pending[infohash][piece_index] = time.time()

        msg = SwarmMessage(
            type="torrent.piece_request",
            payload={"infohash": infohash, "piece_index": piece_index},
            source=self.node_id,
        )
        self.comms.publish_message("torrent.piece_request", msg)

    # ------------------------------------------------------------------
    # Mesh handlers
    # ------------------------------------------------------------------

    def _on_announce(self, msg: SwarmMessage):
        if msg.source == self.node_id:
            return
        payload = msg.payload
        infohash = payload.get("infohash")
        if not infohash:
            return
        self.comms.set_state(f"torrent:{infohash}", payload, expire=3600)
        # A new seeder appeared → bump rarity of every piece a little
        num_pieces = payload.get("num_pieces") or len(payload.get("piece_hashes", []))
        for idx in range(num_pieces):
            self.rarity[infohash][idx] += 1
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
                meta = self.torrents.get(infohash)
                if meta:
                    path = self.storage_dir / f"{infohash}_{meta.name}"
                    if path.exists():
                        data = path.read_bytes()
                        start = idx * meta.piece_size
                        piece_data = data[start : start + meta.piece_size]

            if piece_data:
                # Serving a piece → we know at least one more copy exists
                self.rarity[infohash][idx] += 1

                reply = SwarmMessage(
                    type="torrent.piece_data",
                    payload={
                        "infohash": infohash,
                        "piece_index": idx,
                        "data": piece_data.hex(),
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

        # Clear pending slot regardless
        self.pending[infohash].pop(idx, None)

        if idx in self.have.get(infohash, set()):
            self._fill_pipeline(infohash)  # still try to keep pipeline full
            return

        self.pieces.setdefault(infohash, {})[idx] = data
        self.have.setdefault(infohash, set()).add(idx)
        self.rarity[infohash][idx] += 1  # we now also have it

        have_count = len(self.have[infohash])
        total = len(meta.piece_hashes)

        if self.on_progress:
            self.on_progress(infohash, have_count, total)

        logger.debug(f"Got piece {idx} of {infohash[:12]}… ({have_count}/{total})")

        if have_count == total:
            self._assemble_and_finish(infohash)
        else:
            self._fill_pipeline(infohash)

    def _on_asset_needed(self, msg: SwarmMessage):
        """Scheduler (or anyone) asked for an asset → start download if we can."""
        if msg.source == self.node_id:
            return
        infohash = msg.payload.get("infohash")
        if not infohash:
            return

        # Only act if we don't already have it complete
        if infohash in self.have:
            meta = self.torrents.get(infohash)
            if meta and len(self.have[infohash]) == len(meta.piece_hashes):
                return

        try:
            self.start_download(infohash)
            logger.info(f"Auto-started download for needed asset {infohash[:12]}…")
        except Exception as e:
            logger.debug(f"Could not auto-start {infohash[:12]}: {e}")

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

        # Clear pending
        self.pending.pop(infohash, None)

        if self.on_complete:
            self.on_complete(infohash, dest)


def register_torrent_capability(comms: CommsLayer, extra_caps: Optional[List[str]] = None):
    caps = ["torrent"] + (extra_caps or [])
    comms.register_node(
        node_type="worker",
        capabilities=caps,
        metadata={"torrent_version": "0.2.0"},
    )
    logger.info(f"Registered torrent capability on {comms.node_id}")
