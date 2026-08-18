# btc_anchor  v0.3.1

**Bitcoin attestation for Asset Fabric**

## Broadcasters

| Mode | Env | Behavior |
|------|-----|----------|
| null | default | no-op |
| log | `AURORA_BTC_BROADCASTER=log` | builds OP_RETURN, logs, synthetic txid |
| cli | `AURORA_BTC_BROADCASTER=cli` | bitcoin-cli path; dry-run unless `AURORA_BTC_CLI_SEND=1` |

CLI send path: `createrawtransaction` (data) → `fundrawtransaction` → `signrawtransactionwithwallet` → `sendrawtransaction`.

## Batch

```python
anchor.process_queue_batched()  # Merkle root, one write, proofs on each record
```

## Verify

```python
from mods.btc_anchor.verify import verify_commitment, verify_op_return_prefix, verify_merkle_inclusion
```
