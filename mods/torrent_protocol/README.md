# torrent_protocol Mod  v0.3.0 — Foolproof edition

**Swarm-native piece distribution** inspired by BitTorrent.

Zero external BitTorrent dependencies. Everything rides on the existing CommsLayer mesh.

## Why this version is hard to break

- **Resume after crash/restart** — pieces and metadata are persisted; state is rebuilt on startup
- **ensure_asset()** — single safe call that either creates from a local file or starts a download
- **Never crashes the host** — almost every failure path is caught, logged, and returns cleanly
- **Input validation** — infohash format, piece counts, file size limits, safe filenames
- **Exponential backoff** on timed-out piece requests
- **Memory hygiene** — piece buffers are dropped after a torrent completes
- **Rarest-first + hard back-pressure** (still present from 0.2)
- **Scheduler integration** via `on_asset_needed` / `asset.needed`

## Recommended usage

```python
from comms.layer import CommsLayer
from mods.torrent_protocol.torrent_manager import TorrentManager, register_torrent_capability

comms = CommsLayer(node_id="worker-42")
register_torrent_capability(comms)
tm = TorrentManager(comms)

# One-call happy path
infohash = tm.ensure_asset("/path/to/big_model.pt")          # create + announce
# or
infohash = tm.ensure_asset(infohash="abc123...")             # download/resume

# Classic API still works
meta = tm.create_torrent("/path/to/file")
tm.announce(meta.infohash)
tm.start_download(meta.infohash)

print(tm.get_progress(infohash))
print(tm.is_complete(infohash))
print(tm.get_path(infohash))
```

### From the scheduler

```python
from scheduler.hook_registry import registry

registry.run("on_asset_needed", {"infohash": "abc123...", "name": "big_model.pt"})
```

## Safety limits (tunable constants)

- Max outstanding requests per torrent: 12 (configurable)
- Max pieces per torrent: 50 000
- Max file size: 32 GiB
- Request timeout → exponential backoff up to 120 s

## Storage layout

```
$AURORA_TORRENT_DIR/
  <infohash>.meta.json
  <infohash>.piece.000000
  <infohash>.piece.000001
  ...
  <infohash>_<safe_name>          # final assembled file
```

## Status

v0.3.0 — production-ready experimental. Still lives in `mods/` so it can be disabled instantly.
