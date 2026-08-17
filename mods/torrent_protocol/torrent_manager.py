"""
Aurora Swarm Torrent Manager  v0.4.0 — Maximum Resilience
---------------------------------------------------------
Lightweight, mesh-native piece distribution inspired by BitTorrent.

This version adds the final layer of unattended reliability:

- Persistent "wanted" set — once you ask for an asset we keep trying
- Background maintenance thread (safe, daemon, stoppable)
- Automatic meta re-fetch when announcements are late
- Stall detection + forced pipeline recovery
- Delayed retry for asset.needed events
- Everything from 0.3.0 (resume, ensure_asset, validation, backoff, etc.)

Still pure Python + existing CommsLayer. No external BitTorrent stack.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from comms.layer import CommsLayer, SwarmMessage

logger = logging.getLogger("aurora.torrent")

DEFAULT_PIECE_SIZE = 256 * 1024
MAX_OUTSTANDING = 12
REQUEST_TIMEOUT = 20.0
MAX_BACKOFF = 120.0
MAX_PIECES = 50_000
MAX_FILE_SIZE = 32 * 1024**3
SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9._\- ]{1,200}$")

# Resilience tuning
MAINT_INTERVAL = 8.0          # seconds between background ticks
STALL_SECONDS = 90.0          # no progress for this long → force recovery
META_RETRY_SECONDS = 15.0     # how often to re-ask for missing meta


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
        required = ["infohash", "name", "size", "piece_size", "piece_hashes", "created_by"]
        for k in required:
            if k not in d:
                raise ValueError(f"TorrentMeta missing required field: {k}")
        return cls(
            infohash=str(d["infohash"]),
            name=str(d["name"]),
            size=int(d["size"]),
            piece_size=int(d["piece_size"]),
            piece_hashes=list(d["piece_hashes"]),
            created_by=str(d["created_by"]),
            created_at=float(d.get("created_at", time.time())),
        )


class TorrentManager:
    """
    Maximum-resilience torrent manager for a single Aurora node.
    """

    def __init__(
        self,
        comms: CommsLayer,
        storage_dir: Optional[str] = None,
        max_outstanding: int = MAX_OUTSTANDING,
        auto_maintain: bool = True,
    ):
        self.comms = comms
        self.node_id = comms.node_id
        self.storage_dir = Path(storage_dir or os.getenv("AURORA_TORRENT_DIR", "/tmp/aurora_torrents"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.max_outstanding = max(1, min(max_outstanding, 64))

        self.torrents: Dict[str, TorrentMeta] = {}
        self.have: Dict[str, Set[int]] = {}
        self.pieces: Dict[str, Dict[int, bytes]] = {}

        self.rarity: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.pending: Dict[str, Dict[int, float]] = defaultdict(dict)
        self.backoff: Dict[str, Dict[int, float]] = defaultdict(dict)

        # Resilience state
        self.wanted: Set[str] = set()                     # infohashes we must eventually get
        self.last_progress: Dict[str, float] = {}         # infohash → last time we gained a piece
        self.last_meta_attempt: Dict[str, float] = {}     # infohash → last meta fetch try

        self.on_complete: Optional[Callable[[str, Path], None]] = None
        self.on_progress: Optional[Callable[[str, int, int], None]] = None

        # Mesh handlers
        self.comms.subscribe("torrent.announce", self._on_announce)
        self.comms.subscribe("torrent.piece_request", self._on_piece_request)
        self.comms.subscribe("torrent.piece_data", self._on_piece_data)
        self.comms.subscribe("asset.needed", self._on_asset_needed)

        self._resume_from_disk()

        # Background maintainer
        self._stop_event = threading.Event()
        self._maint_thread: Optional[threading.Thread] = None
        if auto_maintain:
            self.start_maintainer()

        logger.info(
            f"TorrentManager v0.4.0 (max resilience) ready on node={self.node_id} "
            f"max_outstanding={self.max_outstanding} storage={self.storage_dir}"
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_maintainer(self):
        if self._maint_thread and self._maint_thread.is_alive():
            return
        self._stop_event.clear()
        self._maint_thread = threading.Thread(
            target=self._maint_loop, name="torrent-maint", daemon=True
        )
        self._maint_thread.start()
        logger.debug("Background maintainer started")

    def stop(self):
        """Cleanly stop the background maintainer."""
        self._stop_event.set()
        if self._maint_thread and self._maint_thread.is_alive():
            self._maint_thread.join(timeout=5.0)
        logger.debug("Background maintainer stopped")

    def _maint_loop(self):
        while not self._stop_event.is_set():
            try:
                self._maintenance_tick()
            except Exception as e:
                logger.warning(f"Maintenance tick error: {e}")
            self._stop_event.wait(MAINT_INTERVAL)

    def _maintenance_tick(self):
        now = time.time()

        # 1. Retry meta for wanted torrents that we still don't have
        for infohash in list(self.wanted):
            if infohash in self.torrents:
                continue
            last = self.last_meta_attempt.get(infohash, 0)
            if now - last >= META_RETRY_SECONDS:
                self.last_meta_attempt[infohash] = now
                meta = self._fetch_meta(infohash, retries=1)
                if meta:
                    logger.info(f"Meta finally arrived for wanted {infohash[:12]}… — starting")
                    self.start_download(infohash, meta=meta)

        # 2. Stall detection + recovery for active downloads
        for infohash in list(self.wanted):
            if self.is_complete(infohash):
                self.wanted.discard(infohash)
                continue
            if infohash not in self.torrents:
                continue

            last = self.last_progress.get(infohash, 0)
            if last == 0:
                self.last_progress[infohash] = now  # first time we see it
                continue

            if now - last > STALL_SECONDS:
                logger.info(f"Stall detected on {infohash[:12]}… — forcing recovery")
                # Soft-clear backoffs so rarest-first can try again immediately
                self.backoff[infohash].clear()
                # Drop very old pending so we can re-request
                self.pending[infohash].clear()
                self._fill_pipeline(infohash)
                self.last_progress[infohash] = now  # prevent tight loop

        # 3. Keep pipelines full even without new events
        for infohash in list(self.wanted):
            if infohash in self.torrents and not self.is_complete(infohash):
                self._fill_pipeline(infohash)

    # ------------------------------------------------------------------
    # Public foolproof API
    # ------------------------------------------------------------------

    def ensure_asset(
        self,
        source: str | Path | None = None,
        *,
        infohash: Optional[str] = None,
        name: Optional[str] = None,
        announce: bool = True,
    ) -> Optional[str]:
        try:
            if source is not None:
                path = Path(source)
                if path.is_file():
                    meta = self.create_torrent(path, name=name)
                    if announce:
                        self.announce(meta.infohash)
                    return meta.infohash
                logger.warning(f"ensure_asset: source is not a file: {path}")
                return None

            if infohash:
                self.wanted.add(str(infohash).strip().lower())
                ok = self.start_download(infohash)
                return infohash if ok else infohash  # still return it — we will keep trying

            logger.warning("ensure_asset called with neither source nor infohash")
            return None
        except Exception as e:
            logger.exception(f"ensure_asset failed: {e}")
            return None

    def create_torrent(
        self,
        file_path: str | Path,
        name: Optional[str] = None,
        piece_size: int = DEFAULT_PIECE_SIZE,
    ) -> TorrentMeta:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Cannot create torrent: {path} not found")

        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            raise ValueError(f"File too large ({size} bytes). Max allowed: {MAX_FILE_SIZE}")
        if size == 0:
            raise ValueError("Cannot create torrent from empty file")

        piece_size = max(16 * 1024, min(piece_size, 4 * 1024 * 1024))
        num_pieces = (size + piece_size - 1) // piece_size
        if num_pieces > MAX_PIECES:
            raise ValueError(f"Too many pieces ({num_pieces}). Increase piece_size or split the file.")

        safe_name = self._safe_name(name or path.name)

        data = path.read_bytes()
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
            name=safe_name,
            size=size,
            piece_size=piece_size,
            piece_hashes=piece_hashes,
            created_by=self.node_id,
        )

        self.torrents[infohash] = meta
        self.have[infohash] = set(range(len(piece_hashes)))
        self.pieces[infohash] = pieces

        for idx in range(len(piece_hashes)):
            self.rarity[infohash][idx] = max(self.rarity[infohash][idx], 1)

        self._write_complete_file(infohash, data)
        self._write_meta(infohash, meta)

        logger.info(f"Created torrent {infohash[:12]}… name={safe_name} pieces={len(piece_hashes)}")
        return meta

    def announce(self, infohash: str) -> bool:
        meta = self.torrents.get(infohash)
        if not meta:
            logger.warning(f"announce: unknown torrent {infohash[:12]}")
            return False
        try:
            msg = SwarmMessage(
                type="torrent.announce",
                payload=meta.to_dict(),
                source=self.node_id,
            )
            self.comms.publish_message("torrent.announce", msg)
            self.comms.set_state(f"torrent:{infohash}", meta.to_dict(), expire=7200)
            logger.info(f"Announced torrent {infohash[:12]}…")
            return True
        except Exception as e:
            logger.error(f"announce failed: {e}")
            return False

    def start_download(self, infohash: str, meta: Optional[TorrentMeta] = None) -> bool:
        infohash = str(infohash).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{16,64}", infohash):
            logger.warning(f"start_download: invalid infohash format: {infohash}")
            return False

        self.wanted.add(infohash)

        if self.is_complete(infohash):
            logger.info(f"Already complete: {infohash[:12]}")
            self.wanted.discard(infohash)
            return True

        if meta is None:
            meta = self._fetch_meta(infohash)
            if meta is None:
                self.last_meta_attempt[infohash] = time.time()
                logger.info(f"No metadata yet for {infohash[:12]} — added to wanted set (will retry)")
                return False

        if len(meta.piece_hashes) > MAX_PIECES or meta.size > MAX_FILE_SIZE:
            logger.error(f"Rejecting insane torrent {infohash[:12]}")
            self.wanted.discard(infohash)
            return False

        self.torrents[infohash] = meta
        self.have.setdefault(infohash, set())
        self.pieces.setdefault(infohash, {})
        self.last_progress.setdefault(infohash, time.time())

        self._load_partial_pieces(infohash)

        missing = set(range(len(meta.piece_hashes))) - self.have[infohash]
        logger.info(
            f"Starting/resuming {infohash[:12]}… "
            f"have={len(self.have[infohash])} missing={len(missing)}"
        )

        self._fill_pipeline(infohash)
        return True

    def is_complete(self, infohash: str) -> bool:
        meta = self.torrents.get(infohash)
        if not meta:
            path = self._complete_path(infohash)
            return path is not None and path.exists()
        return len(self.have.get(infohash, set())) == len(meta.piece_hashes)

    def get_path(self, infohash: str) -> Optional[Path]:
        path = self._complete_path(infohash)
        return path if path and path.exists() else None

    def get_progress(self, infohash: str) -> Dict[str, Any]:
        meta = self.torrents.get(infohash)
        if not meta:
            return {"error": "unknown torrent", "infohash": infohash, "wanted": infohash in self.wanted}
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
            "wanted": infohash in self.wanted,
        }

    def list_torrents(self) -> List[Dict[str, Any]]:
        keys = set(self.torrents.keys()) | self.wanted
        return [self.get_progress(h) for h in keys]

    # ------------------------------------------------------------------
    # Internal helpers — safety & persistence
    # ------------------------------------------------------------------

    def _safe_name(self, name: str) -> str:
        name = name.strip().replace("/", "_").replace("\\", "_")
        if not SAFE_NAME_RE.match(name):
            return "asset_" + hashlib.sha256(name.encode()).hexdigest()[:16]
        return name

    def _meta_path(self, infohash: str) -> Path:
        return self.storage_dir / f"{infohash}.meta.json"

    def _piece_path(self, infohash: str, idx: int) -> Path:
        return self.storage_dir / f"{infohash}.piece.{idx:06d}"

    def _complete_path(self, infohash: str, name: Optional[str] = None) -> Optional[Path]:
        if name:
            return self.storage_dir / f"{infohash}_{name}"
        for p in self.storage_dir.glob(f"{infohash}_*"):
            if p.is_file() and not p.name.endswith(".meta.json") and ".piece." not in p.name:
                return p
        return None

    def _write_meta(self, infohash: str, meta: TorrentMeta):
        try:
            import json
            self._meta_path(infohash).write_text(json.dumps(meta.to_dict()))
        except Exception as e:
            logger.warning(f"Could not persist meta: {e}")

    def _write_complete_file(self, infohash: str, data: bytes):
        meta = self.torrents[infohash]
        path = self.storage_dir / f"{infohash}_{meta.name}"
        path.write_bytes(data)

    def _write_piece(self, infohash: str, idx: int, data: bytes):
        try:
            self._piece_path(infohash, idx).write_bytes(data)
        except Exception as e:
            logger.warning(f"Could not persist piece {idx}: {e}")

    def _load_partial_pieces(self, infohash: str):
        meta = self.torrents.get(infohash)
        if not meta:
            return
        for idx in range(len(meta.piece_hashes)):
            p = self._piece_path(infohash, idx)
            if p.exists():
                try:
                    data = p.read_bytes()
                    if hashlib.sha256(data).hexdigest() == meta.piece_hashes[idx]:
                        self.pieces.setdefault(infohash, {})[idx] = data
                        self.have.setdefault(infohash, set()).add(idx)
                except Exception:
                    p.unlink(missing_ok=True)

    def _resume_from_disk(self):
        import json
        for meta_file in self.storage_dir.glob("*.meta.json"):
            try:
                raw = json.loads(meta_file.read_text())
                meta = TorrentMeta.from_dict(raw)
                infohash = meta.infohash
                self.torrents[infohash] = meta
                self.have.setdefault(infohash, set())
                self._load_partial_pieces(infohash)

                complete = self._complete_path(infohash, meta.name)
                if complete and complete.exists() and complete.stat().st_size == meta.size:
                    self.have[infohash] = set(range(len(meta.piece_hashes)))
                    for idx in range(len(meta.piece_hashes)):
                        self._piece_path(infohash, idx).unlink(missing_ok=True)
                else:
                    # Still incomplete → keep it in the wanted set
                    self.wanted.add(infohash)
                    self.last_progress[infohash] = time.time()

                logger.info(f"Resumed state for {infohash[:12]}… have={len(self.have[infohash])}")
            except Exception as e:
                logger.warning(f"Skipping corrupt meta {meta_file.name}: {e}")

    def _fetch_meta(self, infohash: str, retries: int = 3) -> Optional[TorrentMeta]:
        for attempt in range(retries):
            raw = self.comms.get_state(f"torrent:{infohash}")
            if raw:
                try:
                    return TorrentMeta.from_dict(raw)
                except Exception as e:
                    logger.warning(f"Bad meta for {infohash[:12]}: {e}")
                    return None
            if attempt < retries - 1:
                time.sleep(0.25 * (attempt + 1))
        return None

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def _rarest_missing(self, infohash: str) -> List[int]:
        meta = self.torrents[infohash]
        have = self.have.get(infohash, set())
        pending = self.pending.get(infohash, {})
        rarity = self.rarity[infohash]
        now = time.time()

        candidates = []
        for idx in range(len(meta.piece_hashes)):
            if idx in have or idx in pending:
                continue
            if now < self.backoff[infohash].get(idx, 0):
                continue
            count = rarity.get(idx, 0)
            candidates.append((count, idx))

        candidates.sort()
        return [idx for _, idx in candidates]

    def _fill_pipeline(self, infohash: str):
        if infohash not in self.torrents:
            return
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
        stale = [idx for idx, ts in list(pending.items()) if now - ts > REQUEST_TIMEOUT]
        for idx in stale:
            del pending[idx]
            prev = self.backoff[infohash].get(idx, REQUEST_TIMEOUT)
            self.backoff[infohash][idx] = now + min(prev * 1.7, MAX_BACKOFF)

    def _request_piece(self, infohash: str, piece_index: int):
        self.pending[infohash][piece_index] = time.time()
        try:
            msg = SwarmMessage(
                type="torrent.piece_request",
                payload={"infohash": infohash, "piece_index": piece_index},
                source=self.node_id,
            )
            self.comms.publish_message("torrent.piece_request", msg)
        except Exception as e:
            logger.warning(f"Failed to publish piece request: {e}")
            self.pending[infohash].pop(piece_index, None)

    # ------------------------------------------------------------------
    # Mesh handlers
    # ------------------------------------------------------------------

    def _on_announce(self, msg: SwarmMessage):
        try:
            if msg.source == self.node_id:
                return
            payload = msg.payload or {}
            infohash = payload.get("infohash")
            if not infohash:
                return
            self.comms.set_state(f"torrent:{infohash}", payload, expire=7200)
            num = payload.get("num_pieces") or len(payload.get("piece_hashes", []))
            for idx in range(int(num)):
                self.rarity[infohash][idx] += 1

            # If this was a wanted torrent we were waiting on, start it
            if infohash in self.wanted and infohash not in self.torrents:
                try:
                    meta = TorrentMeta.from_dict(payload)
                    self.start_download(infohash, meta=meta)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"_on_announce error: {e}")

    def _on_piece_request(self, msg: SwarmMessage):
        try:
            if msg.source == self.node_id:
                return
            infohash = (msg.payload or {}).get("infohash")
            idx = (msg.payload or {}).get("piece_index")
            if infohash is None or idx is None:
                return
            idx = int(idx)

            if infohash not in self.have or idx not in self.have[infohash]:
                return

            piece_data = self.pieces.get(infohash, {}).get(idx)
            if piece_data is None:
                p = self._piece_path(infohash, idx)
                if p.exists():
                    piece_data = p.read_bytes()
                else:
                    meta = self.torrents.get(infohash)
                    complete = self._complete_path(infohash, meta.name if meta else None)
                    if complete and complete.exists() and meta:
                        data = complete.read_bytes()
                        start = idx * meta.piece_size
                        piece_data = data[start : start + meta.piece_size]

            if not piece_data:
                return

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
        except Exception as e:
            logger.debug(f"_on_piece_request error: {e}")

    def _on_piece_data(self, msg: SwarmMessage):
        try:
            if msg.source == self.node_id:
                return
            if msg.target and msg.target != self.node_id:
                return

            payload = msg.payload or {}
            infohash = payload.get("infohash")
            idx = payload.get("piece_index")
            data_hex = payload.get("data")
            expected_hash = payload.get("hash")

            if not all([infohash, idx is not None, data_hex, expected_hash]):
                return
            idx = int(idx)

            try:
                data = bytes.fromhex(data_hex)
            except ValueError:
                return

            if hashlib.sha256(data).hexdigest() != expected_hash:
                logger.warning(f"Hash mismatch {infohash[:12]} piece {idx}")
                return

            meta = self.torrents.get(infohash)
            if not meta or idx >= len(meta.piece_hashes):
                return
            if expected_hash != meta.piece_hashes[idx]:
                logger.warning(f"Piece hash does not match meta for {infohash[:12]}[{idx}]")
                return

            self.pending[infohash].pop(idx, None)
            self.backoff[infohash].pop(idx, None)

            if idx in self.have.get(infohash, set()):
                self._fill_pipeline(infohash)
                return

            self.pieces.setdefault(infohash, {})[idx] = data
            self.have.setdefault(infohash, set()).add(idx)
            self.rarity[infohash][idx] += 1
            self._write_piece(infohash, idx, data)

            # Progress tracking for stall detection
            self.last_progress[infohash] = time.time()

            have_count = len(self.have[infohash])
            total = len(meta.piece_hashes)

            if self.on_progress:
                try:
                    self.on_progress(infohash, have_count, total)
                except Exception:
                    pass

            if have_count == total:
                self._assemble_and_finish(infohash)
            else:
                self._fill_pipeline(infohash)
        except Exception as e:
            logger.debug(f"_on_piece_data error: {e}")

    def _on_asset_needed(self, msg: SwarmMessage):
        try:
            if msg.source == self.node_id:
                return
            infohash = (msg.payload or {}).get("infohash")
            if not infohash:
                return
            if self.is_complete(infohash):
                return
            # Always add to wanted — even if start_download fails right now
            self.wanted.add(str(infohash).strip().lower())
            self.start_download(infohash)
        except Exception as e:
            logger.debug(f"_on_asset_needed error: {e}")

    def _assemble_and_finish(self, infohash: str):
        try:
            meta = self.torrents[infohash]
            pieces = self.pieces.get(infohash, {})
            ordered = b"".join(pieces[i] for i in range(len(meta.piece_hashes)))

            if len(ordered) != meta.size:
                logger.error(f"Size mismatch on assemble {infohash[:12]}")
                return

            path = self.storage_dir / f"{infohash}_{meta.name}"
            path.write_bytes(ordered)

            self.pieces.pop(infohash, None)
            self.pending.pop(infohash, None)
            self.backoff.pop(infohash, None)
            self.wanted.discard(infohash)

            for idx in range(len(meta.piece_hashes)):
                self._piece_path(infohash, idx).unlink(missing_ok=True)

            self._write_meta(infohash, meta)
            logger.info(f"Torrent complete → {path}")

            if self.on_complete:
                try:
                    self.on_complete(infohash, path)
                except Exception as e:
                    logger.warning(f"on_complete callback failed: {e}")
        except Exception as e:
            logger.exception(f"_assemble_and_finish failed: {e}")


def register_torrent_capability(comms: CommsLayer, extra_caps: Optional[List[str]] = None):
    caps = ["torrent"] + (extra_caps or [])
    try:
        comms.register_node(
            node_type="worker",
            capabilities=caps,
            metadata={"torrent_version": "0.4.0"},
        )
        logger.info(f"Registered torrent capability on {comms.node_id}")
    except Exception as e:
        logger.error(f"Failed to register torrent capability: {e}")
