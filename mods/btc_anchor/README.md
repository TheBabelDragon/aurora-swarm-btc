# btc_anchor  v0.2.0

**Bitcoin attestation path for Asset Fabric**

Bitcoin is the *settlement / truth* surface. The swarm data plane stays off-chain.

## Pipeline

```
AssetManifest
    → commitment (SHA-256 canonical fields)
    → mesh AnchorRecord          (always)
    → BroadcastQueue             (optional)
    → Broadcaster                (log | null | future wallet)
    → mark_broadcast(txid)       (upgrade status)
```

## On-chain payload (v1)

OP_RETURN short form (24 bytes):

```
AURORA1|<16-hex commitment prefix>
```

Full indexer form is available off-chain via `payload.full_record_json`.

## Usage

```python
from mods.btc_anchor.anchor import AssetAnchor

anchor = AssetAnchor(comms)

# Mesh attestation only
rec = anchor.anchor_manifest(manifest)

# Mesh + enqueue for broadcast
rec = anchor.anchor_manifest(manifest, request_broadcast=True)

# Or later:
anchor.request_broadcast(asset_id)
anchor.process_queue()   # runs LogBroadcaster / Null / future writer
```

## Config

| Env | Meaning |
|-----|--------|
| `AURORA_BTC_ANCHOR_BROADCAST=1` | Prefer LogBroadcaster when mode unset |
| `AURORA_BTC_BROADCASTER=log\|null` | Explicit writer |
| `AURORA_BTC_NETWORK=signet\|testnet\|mainnet` | Label for records |

## Extending to real Bitcoin

Implement `Broadcaster.broadcast(record) -> BroadcastResult` with a wallet/RPC,
return a real `txid`, and `process_queue` / `mark_broadcast` will upgrade the mesh record to `confirmed`.

## Status

v0.2.0 — full path through queue + pluggable writer. Log writer proves payload shape. Real chain writer still a deliberate next plug-in.
