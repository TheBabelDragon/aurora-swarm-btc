# asset_fabric  v0.1.2

**Content-addressed swarm Asset Fabric**

## Public verbs

```python
from mods.asset_fabric.fabric import AssetFabric

fabric = AssetFabric(comms)

asset_id = fabric.publish("/path/to/model.pt", asset_type="model", anchor=True)
fabric.ensure(asset_id)

# Local view
print(fabric.possession(asset_id))

# Swarm view — who holds this?
print(fabric.swarm_possession(asset_id))
# → { asset_id, holders: ["node-A", "node-B"], holder_count: 2 }

# Advertise what this node holds (call periodically)
fabric.publish_possession_snapshot()
```

## Swarm possession

Each node writes a short-TTL snapshot:

```
asset:possession:<node_id> → { assets: [...], names: {...}, updated_at }
```

`swarm_possession` / `list_swarm_assets` scan those keys.  
This is the foundation for replication policy and “move compute toward data.”

## Layering

```
AssetFabric
  ├── TorrentManager   (piece transport)
  └── AssetAnchor      (optional attestation)
         │
         ▼
  CommsLayer mesh  →  collective possession map
```

## Status

v0.1.2 — ensure/publish/possession + swarm holder view. Still experimental (mods/).
