# torrent_protocol Mod  v0.4.0 — Maximum Resilience

**Swarm-native piece distribution** inspired by BitTorrent.

> **Prefer the higher-level API.**  
> New code should speak through `mods.asset_fabric` (`ensure`, `publish`, `possession`).  
> This module is the current **transport implementation** of the Asset Fabric.

Zero external BitTorrent dependencies. Everything rides on the existing CommsLayer mesh.

## Why this is the strongest version

| Feature | Status |
|---------|--------|
| Resume after crash | ✅ |
| `ensure_asset()` one-call API | ✅ |
| Input validation + size limits | ✅ |
| Rarest-first + back-pressure | ✅ |
| Exponential piece backoff | ✅ |
| Persistent wanted set | ✅ |
| Background maintainer | ✅ |
| Automatic meta re-fetch | ✅ |
| Stall detection + recovery | ✅ |
| Scheduler `on_asset_needed` | ✅ |

## Recommended usage (transport level)

For most callers, use Asset Fabric instead:

```python
from mods.asset_fabric.fabric import AssetFabric
fabric = AssetFabric(comms)
asset_id = fabric.publish("/path/to/model.pt", asset_type="model")
fabric.ensure(asset_id)
```

Direct transport usage (still supported):

```python
from mods.torrent_protocol.torrent_manager import TorrentManager, register_torrent_capability

comms = CommsLayer(node_id="worker-42")
register_torrent_capability(comms)
tm = TorrentManager(comms)

infohash = tm.ensure_asset(infohash="abc123...")
# or create from local file
infohash = tm.ensure_asset("/path/to/big_model.pt")
```

### From the scheduler

```python
registry.run("on_asset_needed", {"infohash": "abc123...", "name": "big_model.pt"})
```

## Background behaviour

Every ~8 seconds the maintainer:

1. Re-fetches metadata for any wanted torrent that still lacks it
2. Detects stalls (no new pieces for 90 s) and forces a recovery
3. Keeps request pipelines full

## Status

v0.4.0 — transport implementation under Asset Fabric. Still experimental (mods/).
