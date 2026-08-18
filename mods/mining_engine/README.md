# mining_engine

**Tandem mining:** GPU hashing stays in **bfgminer**; Aurora owns the brain.

```text
bfgminer (OpenCL SHA256d)
    │ stdout shares / hashrate
    ▼
SharePipeline ──► mining_provenance (observed → pool_accepted)
    │
AdaptiveIntensity ◄── thermal hints (optional)
    │
MiningCoordinator ──► Redis fleet view
    │
Dashboard / mesh commands
```

## Not in scope (honest)

- Replacing bfgminer’s OpenCL kernels with pure-Python SHA256d at GPU speed
- Pretending pool stratum is “solved” without a real hasher

## In scope

- Lifecycle + intensity control
- Share → provenance → BVL claim path
- Adaptive intensity from observed hashrate trend + thermal scale
- Fleet aggregate hashrate without fake numbers

## Worker

`worker/miner_worker.py` drives `MiningEngine`.
