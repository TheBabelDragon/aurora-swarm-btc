# btc_anchor  v0.3.0

**Bitcoin attestation for Asset Fabric**

## Pipeline

```
Manifest → commitment → mesh record → queue
                              ↓
                    single OP_RETURN  or  Merkle batch root
                              ↓
                         Broadcaster (log | null | wallet)
                              ↓
                      mark_broadcast(txid)
```

## Payloads

| Form | Bytes | Content |
|------|-------|--------|
| Single | `AURORA1\|xxxxxxxxxxxxxxxx` | commitment prefix |
| Batch | `AURORA1B\|rootprefix\|N` | Merkle root prefix + count |

## API

```python
anchor.anchor_manifest(manifest, request_broadcast=True)
anchor.process_queue()           # one-by-one
anchor.process_queue_batched()   # Merkle root, one write for many assets
```

## Verify

```python
from mods.btc_anchor.verify import verify_commitment, verify_op_return_prefix, verify_merkle_inclusion
```

## Config

`AURORA_BTC_BROADCASTER=log|null`  ·  `AURORA_BTC_NETWORK=signet|testnet|mainnet`  ·  `AURORA_BTC_ANCHOR_BROADCAST=1`
