"""
Aurora Swarm Torrent Manager  v0.5.0 — Verify-on-receive
---------------------------------------------------------
Lightweight, mesh-native piece distribution inspired by BitTorrent.

Byzantine path (soft): attach_byzantine_receive wraps piece intake so
invalid pieces never become local state; PeerScore records crypto fails.
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

MAINT_INTERVAL = 8.0
STALL_SECONDS = 90.0
META_RETRY_SECONDS = 15.0


@dataclass
class TorrentMeta:
    infohash: str
    name: str
    size: int
    piece_size: int
    piece_hashes: List[str]
    created_by: str
    created_at: float = field(default_factory=time.time)
    merkle_root: str = ""

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
            "merkle_root": self.merkle_root,
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
            merkle_root=str(d.get("merkle_root") or ""),
        )


class TorrentManager:
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

        self.wanted: Set[str] = set()
        self.last_progress: Dict[str, float] = {}
        self.last_meta_attempt: Dict[str, float] = {}

        self.on_complete: Optional[Callable[[str, Path], None]] = None
        self.on_progress: Optional[Callable[[str, int, int], None]] = None

        self.comms.subscribe("torrent.announce", self._on_announce)
        self.comms.subscribe("torrent.piece_request", self._on_piece_request)
        self.comms.subscribe("torrent.piece_data", self._on_piece_data)
        self.comms.subscribe("asset.needed", self._on_asset_needed)

        self._resume_from_disk()

        self._stop_event = threading.Event()
        self._maint_thread: Optional[threading.Thread] = None
        if auto_maintain:
            self.start_maintainer()

        logger.info(
            f"TorrentManager v0.5.0 (verify-on-receive) ready on node={self.node_id} "
            f"max_outstanding={self.max_outstanding} storage={self.storage_dir}"
        )
        try:
            from mods.torrent_protocol.byzantine_receive import attach_byzantine_receive
            attach_byzantine_receive(self)
        except Exception as e:
            logger.debug(f"Byzantine receive not attached: {e}")

    def start_maintainer(self):
        if self._maint_thread and self._maint_thread.is_alive():
            return
        self._stop_event.clear()
        self._maint_thread = threading.Thread(
            target=self._maint_loop, name="torrent-maint", daemon=True
        )
        self._maint_thread.start()

    def stop(self):
        self._stop_event.set()
        if self._maint_thread and self._maint_thread.is_alive():
            self._maint_thread.join(timeout=5.0)

    def _maint_loop(self):
        while not self._stop_event.is_set():
            try:
                self._maintenance_tick()
            except Exception as e:
                logger.warning(f"Maintenance tick error: {e}")
            self._stop_event.wait(MAINT_INTERVAL)

    def _maintenance_tick(self):
        now = time.time()
        for infohash in list(self.wanted):
            if infohash in self.torrents:
                continue
            last = self.last_meta_attempt.get(infohash, 0)
            if now - last >= META_RETRY_SECONDS:
                self.last_meta_attempt[infohash] = now
                meta = self._fetch_meta(infohash, retries=1)
                if meta:
                    self.start_download(infohash, meta=meta)
        for infohash in list(self.wanted):
            if self.is_complete(infohash):
                self.wanted.discard(infohash)
                continue
            if infohash not in self.torrents:
                continue
            last = self.last_progress.get(infohash, 0)
            if last == 0:
                self.last_progress[infohash] = now
                continue
            if now - last > STALL_SECONDS:
                logger.info(f"Stall detected on {infohash[:12]}… — forcing recovery")
                self.backoff[infohash].clear()
                self.pending[infohash].clear()
                self._fill_pipeline(infohash)
                self.last_progress[infohash] = now
        for infohash in list(self.wanted):
            if infohash in self.torrents and not self.is_complete(infohash):
                self._fill_pipeline(infohash)

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
                return None
            if infohash:
                self.wanted.add(str(infohash).strip().lower())
                self.start_download(infohash)
                return infohash
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
            raise ValueError(f"File too large ({size} bytes)")
        if size == 0:
            raise ValueError("Cannot create torrent from empty file")
        piece_size = max(16 * 1024, min(piece_size, 4 * 1024 * 1024))
        num_pieces = (size + piece_size - 1) // piece_size
        if num_pieces > MAX_PIECES:
            raise ValueError(f"Too many pieces ({num_pieces})")
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
        mroot = ""
        try:
            from mods.asset_fabric.merkle_pieces import merkle_root_from_piece_hashes
            mroot = merkle_root_from_piece_hashes(piece_hashes)
        except Exception:
            pass
        meta = TorrentMeta(
            infohash=infohash,
            name=safe_name,
            size=size,
            piece_size=piece_size,
            piece_hashes=piece_hashes,
            created_by=self.node_id,
            merkle_root=mroot,
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
            return False
        try:
            msg = SwarmMessage(type="torrent.announce", payload=meta.to_dict(), source=self.node_id)
            self.comms.publish_message("torrent.announce", msg)
            self.comms.set_state(f"torrent:{infohash}", meta.to_dict(), expire=7200)
            return True
        except Exception as e:
            logger.error(f"announce failed: {e}")
            return False

    def start_download(self, infohash: str, meta: Optional[TorrentMeta] = None) -> bool:
        infohash = str(infohash).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{16,64}", infohash):
            return False
        self.wanted.add(infohash)
        if self.is_complete(infohash):
            self.wanted.discard(infohash)
            return True
        if meta is None:
            meta = self._fetch_meta(infohash)
            if meta is None:
                self.last_meta_attempt[infohash] = time.time()
                return False
        if len(meta.piece_hashes) > MAX_PIECES or meta.size > MAX_FILE_SIZE:
            self.wanted.discard(infohash)
            return False
        if not meta.merkle_root:
            try:
                from mods.asset_fabric.merkle_pieces import merkle_root_from_piece_hashes
                meta.merkle_root = merkle_root_from_piece_hashes(meta.piece_hashes)
            except Exception:
                pass
        self.torrents[infohash] = meta
        self.have.setdefault(infohash, set())
        self.pieces.setdefault(infohash, {})
        self.last_progress.setdefault(infohash, time.time())
        self._load_partial_pieces(infohash)
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
        return {
            "infohash": infohash,
            "name": meta.name,
            "have": have,
            "total": total,
            "pending": len(self.pending.get(infohash, {})),
            "percent": round(100.0 * have / total, 1) if total else 0.0,
            "complete": have == total,
            "wanted": infohash in self.wanted,
        }

    def list_torrents(self) -> List[Dict[str, Any]]:
        keys = set(self.torrents.keys()) | self.wanted
        return [self.get_progress(h) for h in keys]

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
        (self.storage_dir / f"{infohash}_{meta.name}").write_bytes(data)

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
                    self.wanted.add(infohash)
                    self.last_progress[infohash] = time.time()
            except Exception as e:
                logger.warning(f"Skipping corrupt meta {meta_file.name}: {e}")

    def _fetch_meta(self, infohash: str, retries: int = 3) -> Optional[TorrentMeta]:
        for attempt in range(retries):
            raw = self.comms.get_state(f"torrent:{infohash}")
            if raw:
                try:
                    return TorrentMeta.from_dict(raw)
                except Exception:
                    return None
            if attempt < retries - 1:
                time.sleep(0.25 * (attempt + 1))
        return None

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
            candidates.append((rarity.get(idx, 0), idx))
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
            if infohash in self.wanted and infohash not in self.torrents:
                try:
                    self.start_download(infohash, meta=TorrentMeta.from_dict(payload))
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
        """Base handler; Byzantine mixin may wrap this."""
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
                return
            meta = self.torrents.get(infohash)
            if not meta or idx >= len(meta.piece_hashes):
                return
            if expected_hash != meta.piece_hashes[idx]:
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
            metadata={"torrent_version": "0.5.0"},
        )
    except Exception as e:
        logger.error(f"Failed to register torrent capability: {e}")
