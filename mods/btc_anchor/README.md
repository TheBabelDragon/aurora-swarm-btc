# btc_anchor  v0.4.0

**Bitcoin attestation for Asset Fabric**

Bitcoin does not store artifacts. A commitment proves:

> this exact artifact identity was known by epoch X

It does not prove "Bitcoin stores this artifact."

The commitment binds `asset_id`, `manifest_hash`, `artifact_epoch`,
`commitment_version` — never the payload.

`asset_id != anchor_id`. Same artifact + different anchor = same object,
different temporal observation.

## Lifecycle

```
UNANCHORED → COMMITMENT_PENDING → BROADCAST → INCLUDED → CONFIRMED

INCLUDED → REORGED → RE_ANCHOR_REQUIRED
```

A locally observed transaction is not a confirmed anchor. Configurable
confirmation depth (`AURORA_BTC_CONFIRMATION_DEPTH`, default 6) is required
before an anchor is authoritative.

Peer-supplied `btc_height` / `block_hash` is evidence to verify, not truth.

## Broadcasters

| Mode | Env | Behavior |
|------|-----|----------|
| null | default | no-op |
| log | `AURORA_BTC_BROADCASTER=log` | builds OP_RETURN, logs, synthetic txid |
| cli | `AURORA_BTC_BROADCASTER=cli` | bitcoin-cli path; dry-run unless `AURORA_BTC_CLI_SEND=1` |
| simulated | SimulatedBitcoinChain attached | log broadcaster + in-process chain |

CLI send path: `createrawtransaction` (data) → `fundrawtransaction` → `signrawtransactionwithwallet` → `sendrawtransaction`.

## Batch

```python
anchor.process_queue_batched()  # Merkle root, one write, proofs on each record
```

## Chain progress / reorg

```python
anchor.apply_chain_progress()
anchor.handle_reorg()
```

Reorg invalidates canonical status, retains the historical observation,
and marks `RE_ANCHOR_REQUIRED`.

## Verify

```python
from mods.btc_anchor.verify import (
    verify_commitment,
    verify_artifact_commitment,
    verify_anchor_record,
    reject_peer_clock_claim,
)
```
