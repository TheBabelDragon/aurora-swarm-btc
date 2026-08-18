# Byzantine-Tolerant Content-Addressed Data Plane

> **Aurora does not require every node to be trustworthy.
> It requires every piece of state to be verifiable.**

## Content layer

- Manifests + Merkle verify-on-receive
- Mesh challenges (claimed → verified)
- PeerScore (crypto fail ≠ timeout)
- Reed-Solomon erasure (`reed_solomon_v1`)
- **Topology-aware redundancy** (site / power / network / rack)
- **Repair planner** uses verified availability only

## Availability rule

```text
claimed holders  ≠  availability
verified holders =  availability

if verified < policy or diversity floors miss:
    plan_repair → place on nodes that add domains
```

## RS placement

Important assets: `encode_important` → plan_rs_placement across domains →
reconstruct only from verified shards.

## Roadmap

1. ~~Verify-on-receive / challenges / RS~~
2. ~~Topology + verified repair planner~~
3. Automatic redistribute executor (move bytes per plan)
4. Epoch state roots → Bitcoin
