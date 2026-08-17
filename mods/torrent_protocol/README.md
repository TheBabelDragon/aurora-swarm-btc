# torrent_protocol Mod

**Swarm-native piece distribution** inspired by BitTorrent, built entirely on top of the existing CommsLayer mesh.

No external BitTorrent libraries. No trackers. No DHT. Just pure mesh P2P for large files.

## Why?

When the swarm needs to distribute multi-hundred-MB assets (models, GPU binaries, big config packs, etc.) a central download quickly becomes a bottleneck. This mod turns every node that opts in into a potential seeder/leecher.

## Quick Start

```python
from comms.layer import CommsLayer
from mods.torrent_protocol.torrent_manager import TorrentManager, register_torrent_capability

comms = CommsLayer(node_id="worker-42")
register_torrent_capability(comms)          # advertise "torrent" capability

tm = TorrentManager(comms)

# --- Seeder side ---
meta = tm.create_torrent("/path/to/big_model.pt")
tm.announce(meta.infohash)

# --- Leecher side (any other node) ---
tm.start_download(meta.infohash)            # or just the infohash if already announced

# Watch progress
print(tm.get_progress(meta.infohash))
```

## How it works

1. **create_torrent** splits the file into 256 KiB pieces, computes SHA-256 hashes, and derives a deterministic infohash.
2. **announce** publishes the metadata (name, size, piece hashes) onto the mesh and stores it in Redis for late joiners.
3. **start_download** requests missing pieces from any node that has the "torrent" capability and currently holds those pieces.
4. Pieces are verified on arrival. When all pieces are present the file is assembled on disk.
5. The newly completed node can immediately serve pieces to others (natural swarming).

## Message types used on the mesh

- `torrent.announce`
- `torrent.piece_request`
- `torrent.piece_data`

## Storage

Completed and in-progress torrents live under `$AURORA_TORRENT_DIR` (default `/tmp/aurora_torrents`).

## Status

v0.1.0 — experimental but functional prototype.

Future ideas:
- Piece prioritization / rarest-first
- Parallel requests with back-pressure
- Integration with the scheduler so "on_asset_needed" automatically triggers a download
- Optional real BitTorrent fallback (libtorrent) for external magnets

## Development Rules

Same as all other mods: keep experiments here, promote to core only after proven stability.
