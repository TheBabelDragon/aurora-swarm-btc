# BVL — Babel Value Ledger

Mesh credit for **useful swarm work**. Not printable from a terminal.

## How BVL is created

Only the **EconomyReactor** (and other system hooks) mint:

| Event | Reward |
|-------|--------|
| `asset.complete` | `seed_hold` to completing node |
| `asset.anchored` | `attest` to anchoring node |
| uptime tick (system) | small `uptime` credit |

Each `(reason, node_id, asset_id)` claim is granted **at most once**.

## What HTTP can do

| Endpoint | Allowed |
|----------|---------|
| `GET /bvl/status` | read |
| `GET /bvl/ledger` | read |
| `POST /bvl/transfer_safe` | move existing balance (confirm recipient) |
| `POST /bvl/settle` | burn → optional sats bridge |
| `POST /bvl/genesis` | **only** if `AURORA_BVL_ALLOW_GENESIS=1` **and** supply is 0 |

There is **no** public `/bvl/reward_seed` anymore.

## Earn for real

1. Upload & complete an asset on the mesh → `asset.complete` → seed credit  
2. Anchor an asset → `asset.anchored` → attest credit  
3. Transfer only moves what was earned  
