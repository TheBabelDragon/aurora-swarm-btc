# asset_fabric  v0.1.1

**Content-addressed swarm Asset Fabric**

This is the durable systems abstraction.  
`torrent_protocol` is the current transport implementation.  
`btc_anchor` is the optional attestation layer.

## Why this exists

```python
from mods.asset_fabric.fabric import AssetFabric

fabric = AssetFabric(comms)

# Publish into the swarm
asset_id = fabric.publish("/path/to/model.pt", asset_type="model")

# Publish + request mesh attestation (soft dependency on btc_anchor)
asset_id = fabric.publish("/path/to/model.pt", asset_type="model", anchor=True)

# Ensure this node possesses it
fabric.ensure(asset_id, policy={"priority": "high"})

# Possession view (includes anchor status when available)
print(fabric.possession(asset_id))
```

## Core objects

### AssetManifest
Immutable, content-addressed descriptor.

### AssetFabric
| Verb | Meaning |
|------|--------|
| `publish(path, …, anchor=False)` | Create asset + announce; optionally attest |
| `ensure(asset_id\|manifest, policy=…)` | Make this node possess the asset |
| `possession(asset_id)` | Local completeness + optional anchor view |
| `list_assets()` | Everything known locally |
| `get_manifest(asset_id)` | Durable manifest if stored |

## Layering

```
AssetFabric          ← durable public language
    │
    ├── TorrentManager   ← piece transport
    └── AssetAnchor      ← optional attestation (btc_anchor)
            │
            ▼
     CommsLayer mesh  →  (later) Bitcoin settlement
```

## Status

v0.1.1 — ensure/publish/possession + optional anchor path. Still experimental (mods/).
