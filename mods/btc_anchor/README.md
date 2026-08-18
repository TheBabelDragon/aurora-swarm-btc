# btc_anchor  v0.1.0

**Optional attestation layer for Asset Fabric**

Bitcoin is used here as a *settlement / truth* surface, not as the data plane.

## What this does today

1. Builds a **deterministic content commitment** over an `AssetManifest`
2. Records that commitment on the **mesh** (`asset:anchor:<id>`)
3. Publishes an `asset.anchored` event
4. Lets any node (or the dashboard) query anchor status

## What this deliberately does *not* do yet

- Broadcast a real Bitcoin transaction
- Require wallet keys or fees

Those are explicit extension points (`mark_broadcast`, future broadcaster process).

## Why start here

```
AssetFabric.publish / ensure
        │
        ▼
   AssetManifest  ──►  commitment  ──►  mesh record  ──►  (later) on-chain
```

The swarm already has collective memory.  
This adds an optional path for selected memories to gain public, scarce attestation.

## Usage

```python
from mods.btc_anchor.anchor import AssetAnchor
from mods.asset_fabric.fabric import AssetFabric

fabric = AssetFabric(comms)
anchor = AssetAnchor(comms)

asset_id = fabric.publish("/path/to/model.pt", asset_type="model")
manifest = fabric.get_manifest(asset_id)

rec = anchor.anchor_manifest(manifest)
print(rec.commitment, rec.status)

# Later, after a real broadcast:
# anchor.mark_broadcast(asset_id, txid="...", method="op_return")
```

## Commitment

SHA-256 over a canonical JSON of:

- asset_id / content_hash
- size, piece_size, piece_hashes
- asset_type, schema_version

Cosmetic fields do not affect the commitment unless placed in provenance deliberately.

## Status

v0.1.0 — mesh attestation + clean on-chain extension point.  
Still experimental (`mods/`). Promote only after a real broadcaster exists and has soaked.
