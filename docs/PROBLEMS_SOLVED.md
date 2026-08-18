# Pitch problems → repo answers

| Problem | Answer in repo |
|---------|----------------|
| Assets live on “some box” | `fabric.publish` / `ensure` · `important=True` RS shards · `POST /fabric/reconstruct` |
| Trust is SSH & spreadsheets | Verify-on-receive · Merkle · challenges · PeerScore |
| Who holds this? | `GET /fabric/who` — **claimed vs verified** |
| False redundancy | `RepairPlanner` — verified + failure-domain diversity only |
| Incentives stop at the pool | **BVL** mint on seed/attest · optional `settle_to_sats` |
| No external time | **Epoch roots** → `btc_anchor` · `POST /fabric/epoch` |

Rule: **claimed ≠ availability. Verified = availability.**

```bash
# Who holds asset X?
curl 'http://localhost:8000/fabric/who?asset_id=<id>'

# Repair toward policy
curl -F asset_id=<id> -X POST http://localhost:8000/fabric/repair

# Reconstruct important asset from RS shards
curl -F asset_id=<id> -X POST http://localhost:8000/fabric/reconstruct

# Commit epoch root
curl -F broadcast=0 -X POST http://localhost:8000/fabric/epoch
```

Mount: `from fabric_ops import mount_fabric_ops` on the dashboard app.
