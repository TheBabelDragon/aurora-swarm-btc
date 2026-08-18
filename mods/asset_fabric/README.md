# asset_fabric

**Content-addressed swarm Asset Fabric**

> Aurora does not require every node to be trustworthy.
> It requires every piece of state to be verifiable.

## Topology + repair

```python
from mods.asset_fabric.topology import NodeTopology, TopologyRegistry, publish_topology
from mods.asset_fabric.repair import RepairPlanner, RedundancyPolicy, encode_important
from mods.asset_fabric.possession_verify import PossessionTracker

publish_topology(comms)  # AURORA_SITE / POWER / NETWORK / RACK

possession = PossessionTracker()
topo = TopologyRegistry()
planner = RepairPlanner(possession, topo, RedundancyPolicy(
    min_verified_holders=3,
    min_power=2,
    min_network=2,
))

report = planner.availability(asset_id)
# report.ok / report.deficits  — claimed is ignored; verified only

plan = planner.plan_repair(asset_id, candidate_nodes)
rs_plan = planner.plan_rs_placement(asset_id, candidate_nodes)
enc = encode_important(data)  # RS shards for domain placement
```

## Modules

| Module | Role |
|--------|------|
| `fabric` | publish / ensure / possession |
| `merkle_pieces` | Merkle proofs |
| `peer_evidence` | PeerScore |
| `possession_verify` | claimed vs verified |
| `challenge` | mesh challenges |
| `erasure` | Reed-Solomon N+M |
| `topology` | failure domains |
| `repair` | verified availability + placement plans |
