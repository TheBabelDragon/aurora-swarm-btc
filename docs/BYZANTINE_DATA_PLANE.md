# Byzantine-Tolerant Content-Addressed Data Plane

> **Aurora does not require every node to be trustworthy.
> It requires every piece of state to be verifiable.**

## Principle

Never trust a node’s statement about data. Trust independently verifiable content.

## Content layer (no BFT consensus)

- Cryptographic manifests + Merkle trees over pieces
- Verify-on-receive (`torrent` v0.5 + `byzantine_receive`)
- Mesh **challenges** for claimed possession (`asset.challenge`)
- PeerScore: cryptographic failure ≠ timeout
- Erasure coding foundation (`erasure.encode/decode`) — RS upgrade path
- Repair from verified shards only (policy next)

## Claimed vs verified

| Kind | Meaning |
|------|--------|
| Claimed | Node asserts possession |
| Verified | Survived receive-path verify or explicit challenge |

Replication accounting must use verified availability.

## State layer (quorum only when needed)

Authoritative versions, policy epochs, fleet config — not piece validity.

## External attestation

Bitcoin anchors selected roots (supply, registry, policy) — not bulk data.

## Roadmap

1. ~~Verify-on-receive~~
2. ~~Piece challenges~~
3. ~~Erasure interface~~
4. Topology-aware placement (failure domains)
5. Verified-availability repair loop
6. Epoch state roots → `btc_anchor`
