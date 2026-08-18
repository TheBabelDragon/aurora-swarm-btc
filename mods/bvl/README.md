# bvl  v0.1.0 — Babel Value Ledger

**Mesh-native swarm credits for Aurora**

BVL is an internal unit of account for the organism — not a blockchain, not a pump token.

```text
Earn   seed / hold assets · attest · uptime
Hold   per-node balance on CommsLayer
Move   transfer between nodes
Settle optional burn → ln_tips (sats)
```

## Usage

```python
from mods.bvl.ledger_service import BabelLedger

bvl = BabelLedger(comms)

bvl.reward_seed(asset_id="abc…")
bvl.reward_attest(asset_id="abc…")
bvl.score_holders("abc…")          # mint to every holder

print(bvl.balance())
print(bvl.supply())

bvl.transfer("worker-02", 5.0, memo="thanks for the pieces")
bvl.settle_to_sats(3.0, tip_node="worker-02")  # burn BVL, tip sats if ln_tips live
```

## State keys

| Key | Meaning |
|-----|--------|
| `bvl:bal:<node>` | balance |
| `bvl:supply` | circulating mesh supply |
| `bvl:ledger` | recent mint/burn/transfer/settle events |

## Env

| Variable | Default | Meaning |
|----------|---------|--------|
| `AURORA_BVL_SEED_HOLD` | 1.0 | mint per seed score |
| `AURORA_BVL_ATTEST` | 2.0 | mint on attest |
| `AURORA_BVL_UPTIME` | 0.1 | mint per uptime tick |
| `AURORA_BVL_SATS_PER` | 1.0 | BVL→sats ratio on settle |

## Status

v0.1 — experimental mesh credit. Promote only after the earn rules match real swarm behavior.
