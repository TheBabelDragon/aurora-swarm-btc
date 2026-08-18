# asset_fabric

**Content-addressed swarm Asset Fabric**

> Aurora does not require every node to be trustworthy.
> It requires every piece of state to be verifiable.

See [docs/BYZANTINE_DATA_PLANE.md](../../docs/BYZANTINE_DATA_PLANE.md).

## Modules

| Module | Role |
|--------|------|
| `fabric` | publish / ensure / possession |
| `merkle_pieces` | piece Merkle root + proofs |
| `peer_evidence` | local PeerScore |
| `possession_verify` | claimed vs verified |
| `challenge` | mesh piece challenges |
| `erasure` | N+M shard encode/decode foundation |

## Challenge

```python
from mods.asset_fabric.challenge import PieceChallenger

ok = challenger.challenge(asset_id, piece_index=11, target_node="worker-02")
# True → verified possession upgraded; PeerScore success
# False → failed challenge / timeout / invalid bytes
```

## Erasure coding

```python
from mods.asset_fabric.erasure import encode, decode

enc = encode(data, n_data=4, n_parity=2)
# distribute enc["shards"] across failure domains
# recover with decode(shards_or_none, ...)
```

`xor_parity_v1` is a stopgap. Prefer Reed-Solomon before adversarial loss models.
