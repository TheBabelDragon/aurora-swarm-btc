# asset_fabric

**Content-addressed swarm Asset Fabric**

> Aurora does not require every node to be trustworthy.
> It requires every piece of state to be verifiable.

## Repair executor

```python
from mods.asset_fabric.repair_executor import RepairExecutor

execu = RepairExecutor(comms, planner, list_candidates=lambda: node_ids)
execu.run_for_asset(asset_id)   # availability → plan → asset.needed / asset.repair
execu.place_rs(asset_id)        # domain-aware shard placement directives
```

## Epoch roots → Bitcoin

```python
from mods.asset_fabric.epoch import EpochBuilder, commit_epoch

epoch = EpochBuilder(comms).from_local_state(
    possession=manager.possession,
    topology_registry=manager.topology,
    policy=manager.repair_planner.policy,
)
EpochBuilder(comms).commit(epoch, request_broadcast=False)
# or: commit_epoch(comms, possession=..., request_broadcast=True)
```

Roots cover verified registry, topology, policy, optional BVL supply.
Bitcoin timestamps the commitment — not the data plane.

## Modules

| Module | Role |
|--------|------|
| `erasure` | Reed-Solomon |
| `topology` | failure domains |
| `repair` | verified availability plans |
| `repair_executor` | mesh jobs from plans |
| `epoch` | state roots + btc_anchor |
| `challenge` / `merkle_pieces` / `peer_evidence` | Byzantine content path |
