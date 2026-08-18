# asset_fabric

**Content-addressed swarm Asset Fabric**

## Design principle

> Aurora does not require every node to be trustworthy.
> It requires every piece of state to be verifiable.

See [docs/BYZANTINE_DATA_PLANE.md](../../docs/BYZANTINE_DATA_PLANE.md).

## Public verbs

```python
fabric.publish(path)
fabric.ensure(asset_id)
fabric.possession(asset_id)
fabric.swarm_possession(asset_id)  # claimed holders (mesh snapshots)
```

## Byzantine foundation modules

| Module | Role |
|--------|------|
| `merkle_pieces` | Piece Merkle root + inclusion proofs |
| `peer_evidence` | Local PeerScore; crypto fail ≠ timeout |
| `possession_verify` | Claimed vs challenge-verified possession |

**Rule:** reputation ranks peers; hashes decide truth.

## Roadmap (content layer)

1. ~~Manifest + piece hashes~~
2. Merkle proofs on piece receive ← foundation landed
3. Wire torrent transport to reject invalid pieces + PeerScore
4. Erasure coding (N+M) for important assets
5. Topology-aware placement policy
6. State-root attestation epochs → Bitcoin
