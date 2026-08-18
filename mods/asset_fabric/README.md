# asset_fabric  v0.1.0

**Content-addressed swarm Asset Fabric**

This is the durable systems abstraction.  
`torrent_protocol` is the current transport implementation.

## Why this exists

BitTorrent-inspired piece distribution gave us a working data plane.
Asset Fabric turns that into a language the rest of Aurora can speak:

```python
from mods.asset_fabric.fabric import AssetFabric

fabric = AssetFabric(comms)

# Publish a local file into the swarm
asset_id = fabric.publish("/path/to/model.pt", asset_type="model")

# Ensure this node possesses it (pull if missing)
fabric.ensure(asset_id, policy={"priority": "high"})

# Ask the local possession view
print(fabric.possession(asset_id))
```

Callers should prefer `ensure` / `publish` / `possession` over anything that mentions pieces, infohashes, or torrents.

## Core objects

### AssetManifest
Immutable, content-addressed descriptor:

- `asset_id` / `content_hash`
- size, piece_size, piece_hashes
- name, asset_type, schema_version
- created_by, creation_epoch, provenance

### AssetFabric
Public interface:

| Verb | Meaning |
|------|--------|
| `publish(path, …)` | Create asset from local file + announce |
| `ensure(asset_id\|manifest, policy=…)` | Make this node possess the asset |
| `possession(asset_id)` | Local completeness / progress view |
| `list_assets()` | Everything known locally |
| `get_manifest(asset_id)` | Durable manifest if stored |
| `is_complete` / `path` | Convenience |

## Relationship to torrent_protocol

```
AssetFabric          ← durable public language
    │
    ▼
TorrentManager       ← current piece-transport implementation
    │
    ▼
CommsLayer mesh
```

The transport can later be replaced or extended (different piece strategy, real external magnets, erasure coding, etc.) without changing callers of `ensure`.

## Scheduler integration

The existing `on_asset_needed` hook continues to work.  
Prefer speaking in asset terms going forward:

```python
registry.run("on_asset_needed", {"infohash": asset_id, "name": "model.pt"})
# or the alias
registry.run("on_asset_ensure", {"infohash": asset_id})
```

## Status

v0.1.0 — first durable abstraction layer. Still experimental (lives in mods/).  
Promote only the Asset / ensure contracts once they have soaked.
