# torrent_protocol Mod  v0.4.0 — Maximum Resilience

**Swarm-native piece distribution** inspired by BitTorrent.

Zero external BitTorrent dependencies. Everything rides on the existing CommsLayer mesh.

## Why this is the strongest version

| Feature | Status |
|---------|--------|
| Resume after crash | ✅ |
| `ensure_asset()` one-call API | ✅ |
| Input validation + size limits | ✅ |
| Rarest-first + back-pressure | ✅ |
| Exponential piece backoff | ✅ |
| **Persistent wanted set** | ✅ new |
| **Background maintainer** | ✅ new |
| **Automatic meta re-fetch** | ✅ new |
| **Stall detection + recovery** | ✅ new |
| Scheduler `on_asset_needed` | ✅ |

Once you ask for an asset (via `ensure_asset`, `start_download`, or the scheduler hook) the manager will keep trying until it succeeds or you explicitly stop it.

## Recommended usage

```python
from comms.layer import CommsLayer
from mods.torrent_protocol.torrent_manager import TorrentManager, register_torrent_capability

comms = CommsLayer(node_id="worker-42")
register_torrent_capability(comms)

tm = TorrentManager(comms)          # auto-starts background maintainer

# Fire-and-forget — it will keep trying
infohash = tm.ensure_asset(infohash="abc123...")

# Or create + announce
infohash = tm.ensure_asset("/path/to/big_model.pt")

# Later…
print(tm.get_progress(infohash))
print(tm.is_complete(infohash))
print(tm.get_path(infohash))

# Clean shutdown (optional)
tm.stop()
```

### From the scheduler

```python
registry.run("on_asset_needed", {"infohash": "abc123...", "name": "big_model.pt"})
```

The manager adds it to the wanted set and will retry automatically even if metadata is not yet available.

## Background behaviour

Every ~8 seconds the maintainer:

1. Re-fetches metadata for any wanted torrent that still lacks it
2. Detects stalls (no new pieces for 90 s) and forces a recovery
3. Keeps request pipelines full

You can disable the background thread with `TorrentManager(..., auto_maintain=False)` and call a public tick yourself if you prefer full control.

## Status

v0.4.0 — the most robust version yet. Still lives in `mods/` so it can be disabled instantly.
