# btc_identity  v0.1.0

**Bitcoin-style node identity for the Aurora mesh**

## What it does

- Loads or creates per-node key material (`AURORA_NODE_KEY_PATH`)
- Prefers `coincurve` secp256k1 when installed; otherwise a documented dev HMAC backend
- Exposes fingerprint + address-style label for humans and dashboards
- Signs registration claims and publishes them under `node:identity:<node_id>`

## Usage

```python
from mods.btc_identity.identity import NodeIdentity

ident = NodeIdentity(comms)
ident.register_with_identity(capabilities=["gpu_mining", "torrent"])
print(ident.identity_view())
```

## Not a wallet

The address-style string is a **label**, not a guaranteed spendable Bitcoin address
unless you run with a real secp256k1 backend and proper bech32 encoding (future).
It is enough for recognizing nodes across restarts and attaching payment hints later.
