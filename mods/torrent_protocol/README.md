# torrent_protocol Mod  v0.2.0

**Swarm-native piece distribution** inspired by BitTorrent, built entirely on top of the existing CommsLayer mesh.

No external BitTorrent libraries. No trackers. No DHT. Just pure mesh P2P for large files.

## What's new in 0.2.0

- **Rarest-first** piece prioritization (local availability view)
- **Parallel requests** with hard back-pressure (`max_outstanding`, default 12)
- Pending-request tracking + automatic re-request on timeout
- **Scheduler integration** via the `on_asset_needed` hook + `asset.needed` mesh event

## Quick Start

```python
from comms.layer import CommsLayer
from mods.torrent_protocol.torrent_manager import TorrentManager, register_torrent_capability

comms = CommsLayer(node_id="worker-42")
register_torrent_capability(comms)

tm = TorrentManager(comms)          # optional: max_outstanding=16

# Seeder
meta = tm.create_torrent("/path/to/big_model.pt")
tm.announce(meta.infohash)

# Leecher
tm.start_download(meta.infohash)
print(tm.get_progress(meta.infohash))
```

### Triggering a download from the scheduler

```python
from scheduler.hook_registry import registry

# Anywhere in scheduler / control code:
registry.run("on_asset_needed", {"infohash": "abc123...", "name": "big_model.pt"})
```

This publishes an `asset.needed` event. Every live TorrentManager will automatically call `start_download` if it does not already have the complete file.

## How the pipeline works

1. Missing pieces are ordered **rarest-first** using a simple availability counter.
2. Up to `max_outstanding` pieces are requested in parallel.
3. When a piece arrives (or times out) a new rarest piece is requested — the pipeline stays full without flooding the mesh.
4. Completed downloaders immediately become seeders.

## Message types

- `torrent.announce`
- `torrent.piece_request`
- `torrent.piece_data`
- `asset.needed`          ← new (scheduler / anyone)

## Storage

`$AURORA_TORRENT_DIR` (default `/tmp/aurora_torrents`)

## Status

v0.2.0 — solid experimental foundation with the three most requested improvements.

Still experimental. Promote to core only after real-world soak testing.
