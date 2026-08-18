# Byzantine-Tolerant Content-Addressed Data Plane

> **Aurora does not require every node to be trustworthy.
> It requires every piece of state to be verifiable.**

We do **not** make the entire swarm BFT.
We make the **asset fabric** Byzantine-tolerant for content integrity.

## Principle

Never trust a node’s statement about data.  
Trust independently verifiable content.

```text
NODE A ──piece──▶ NODE B
                    │
                    ├── hash(piece)
                    ├── verify Merkle proof against manifest root
                    ├── accept / INVALID_PIECE
                    └── update PeerScore (crypto fail ≠ timeout)
```

A malicious node can send garbage labeled “piece 817.”  
It cannot make garbage validate against the manifest.

## Layers

### Content layer (no BFT consensus)

- Cryptographic manifests (AssetID from content commitment)
- Merkle trees over pieces / shards
- Per-piece verification on receive
- Erasure coding (planned): N data + M parity, any N of N+M reconstruct
- Repair from verified shards only
- Peer evidence for routing preference

### State / metadata layer (quorum only where agreement is required)

- Authoritative version policy for *mutable* logical names
- Replication / diversity policy
- Fleet configuration epochs

Immutable content identity and mutable naming must not be conflated.

```text
Immutable:  AssetID = commitment(manifest + content)
Mutable:    Name → signed version record → AssetID
```

### External attestation (optional)

Bitcoin anchors **state roots / supply roots / policy roots** — not bulk assets.

## Claimed vs verified possession

| Kind | Meaning |
|------|--------|
| Claimed | Node asserts bitmap / possession |
| Verified | Survived challenge (bytes + Merkle proof) |

Replication accounting must use **verified** availability, not claims.

## PeerScore (local evidence)

Track separately:

- successful transfers
- **invalid pieces** (cryptographic failure — strong signal)
- failed challenges
- timeouts / stale responses (network — weak signal)

**Reputation chooses who to ask first. Cryptography decides what is true.**

## Topology-aware redundancy (policy target)

Count diversity across failure domains (power, network, rack, site), not only replica count.

## Repair loop

```text
detect → verify → quarantine bad source → reconstruct → redistribute → verify
```

## Relation to BitTorrent

BitTorrent: the network collectively distributes the file.  
Aurora: the fleet collectively **owns, verifies, repairs, and reasons about** state — even when some members cannot be trusted.

That is collective memory as a distributed-systems property.
