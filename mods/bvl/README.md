# bvl  v0.1.1 — Babel Value Ledger

**Mesh-native swarm credits for Aurora**

```text
Work on the mesh  →  BVL mint  →  optional sats (ln_tips)
                      ↓
              optional supply attestation (btc_anchor)
```

## Live economy

```python
from mods.bvl.economy import start_economy

reactor = start_economy(comms)
# asset.complete  → seed reward
# asset.anchored  → attest reward

reactor.pulse_uptime()     # call from worker loop
reactor.attest_supply()    # commit supply snapshot (mesh + optional BTC anchor)
```

## Manual API (still available)

```python
from mods.bvl.ledger_service import BabelLedger
bvl = BabelLedger(comms)
bvl.score_holders(asset_id)
bvl.transfer("worker-02", 5.0)
bvl.settle_to_sats(3.0)
```

## Status

v0.1.1 — live reactor + supply attestation hook. Experimental (mods/).
