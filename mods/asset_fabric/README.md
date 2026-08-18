# asset_fabric

**Content-addressed swarm Asset Fabric**

> Aurora does not require every node to be trustworthy.
> It requires every piece of state to be verifiable.

See [docs/BYZANTINE_DATA_PLANE.md](../../docs/BYZANTINE_DATA_PLANE.md).

## Erasure coding (Reed-Solomon)

```python
from mods.asset_fabric.erasure import encode, decode, selftest

assert selftest()

enc = encode(data, n_data=4, n_parity=2)
# enc["shards"] → distribute across failure domains
# lose any 2 of 6 → still recovers

shards = list(enc["shards"])
shards[1] = None
shards[5] = None
out = decode(
    shards,
    n_data=enc["n_data"],
    n_parity=enc["n_parity"],
    shard_size=enc["shard_size"],
    original_size=enc["original_size"],
)
assert out == data
```

Code: **`reed_solomon_v1`** — systematic RS over GF(256), pure Python.  
Constraint: `n_data + n_parity ≤ 255`.

## Other modules

| Module | Role |
|--------|------|
| `fabric` | publish / ensure / possession |
| `merkle_pieces` | piece Merkle root + proofs |
| `peer_evidence` | local PeerScore |
| `possession_verify` | claimed vs verified |
| `challenge` | mesh piece challenges |
| `erasure` | Reed-Solomon N+M shards |
