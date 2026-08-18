# Pitch problems → repo answers

| Problem | Answer in repo |
|---------|----------------|
| Assets live on “some box” | `fabric.publish` / `ensure` · `important=True` RS · `POST /fabric/reconstruct` |
| Trust is SSH & spreadsheets | Verify-on-receive · Merkle · challenges · PeerScore |
| Who holds this? | `GET /fabric/who` — **claimed vs verified** |
| False redundancy | `RepairPlanner` — verified + domain diversity |
| Incentives stop at the pool | **BVL** · seed/attest/repair · optional sats |
| No external time | **Epoch roots** → `btc_anchor` |
| Where did the work & reward come from? | **Mining Provenance** (below) |

Rule: **claimed ≠ availability. Verified = availability.**

---

## 5. Where did the work and reward come from?

Aurora records **cryptographically attributable mining observations** alongside worker, epoch, pool, and custody metadata.

**On-chain Bitcoin data remains the authoritative source for transactions and UTXOs.**  
Aurora provides the **operational provenance layer** connecting those events to the physical swarm.

This distinguishes:

| Source | Proves |
|--------|--------|
| Bitcoin | tx/UTXO existence, value movement between scripts |
| Pool | acceptance / account credits (reports) |
| Aurora | worker identity, facility domain, share observations, optional custody *observations* |

Evidence ladder (never skip upward without corroboration):

1. `observed_share`
2. `pool_accepted`
3. `pool_credited`
4. `coinbase_associated` — policy-linked association, **not** a claim that Bitcoin encodes hardware identity

```bash
GET  /mining/who?epoch=1842
GET  /mining/worker/node-17
GET  /mining/reward/<txid>
GET  /mining/provenance/<txid>
GET  /mining/utxo/<txid>/<vout>
POST /mining/observe_share
POST /mining/upgrade
POST /mining/register_worker
```

Custody paths (`treasury / vault-A / policy-7`) are **Aurora observations**, explicitly labeled — never presented as consensus facts.

Babel order remains:

1. Prove who holds the asset  
2. Prove the asset is real  
3. Prove who contributed to maintaining it  
4. Connect economic events to external settlement without lying about what Bitcoin knows  
