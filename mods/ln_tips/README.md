# ln_tips  v0.1.0

**Lightning seeder incentives for the Asset Fabric**

## Idea

Nodes that hold (seed) valuable assets can receive small sat tips.
Policy is simple for v0.1; the ledger and tipper interface are the durable parts.

```python
from mods.ln_tips.service import TipService

tips = TipService(comms)
tips.reward_seeder(asset_id, node_id, amount_sats=25)
tips.reward_holders(asset_id)   # tip everyone in swarm_possession
print(tips.recent())
```

## Tippers

| Mode | Env | Behavior |
|------|-----|----------|
| log | `AURORA_LN_TIPPER=log` (default) | log + ledger entry |
| null | `AURORA_LN_TIPPER=null` | no-op |
| lnd | `AURORA_LN_TIPPER=lnd` | LND REST intent (configure REST + macaroon) |

```bash
export AURORA_LN_TIP_SATS=10
export AURORA_LND_REST=https://127.0.0.1:8080
export AURORA_LND_MACAROON_HEX=...
```

## Status

v0.1 — ledger + policy + pluggable tipper. Real LND pay path is an intentional next plug-in on the same interface.
