# mining_provenance

**Progressive mining evidence — not pretend Bitcoin location.**

| Layer | What it proves |
|-------|----------------|
| Bitcoin | tx/UTXO exists; coins moved between scripts |
| Pool reports | acceptance / credits (operational) |
| Aurora | worker identity, facility domain, share observations, custody *observations* |

Evidence ladder:

1. `observed_share`
2. `pool_accepted`
3. `pool_credited`
4. `coinbase_associated` (policy-linked, never claimed as consensus hardware proof)

```python
from mods.mining_provenance.service import MiningProvenance
from mods.mining_provenance.models import WorkerIdentity, EvidenceLevel

mp = MiningProvenance(comms)
mp.register_worker(WorkerIdentity(
    worker_id="node-17", node_id="node-17",
    facility_domain="AZ-01", pool_id="pool-X",
))
ev = mp.observe_share(worker_id="node-17", epoch=1842, difficulty=1000)
mp.upgrade_evidence(ev.event_id, EvidenceLevel.POOL_ACCEPTED)
```

APIs: see `dashboard/mining_ops.py`.
