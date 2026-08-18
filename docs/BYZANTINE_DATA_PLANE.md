# Byzantine-Tolerant Content-Addressed Data Plane

> **Aurora does not require every node to be trustworthy.
> It requires every piece of state to be verifiable.**

## Stack

| Layer | Mechanism |
|-------|-----------|
| Integrity | Merkle verify-on-receive |
| Possession | claimed vs challenge-verified |
| Evidence | PeerScore (crypto ≠ timeout) |
| Durability | Reed-Solomon N+M |
| Placement | topology diversity |
| Repair | verified-only planner + executor |
| Attestation | epoch roots → btc_anchor → Bitcoin |

## Epoch commitment

```text
verified registry root
topology root
policy root
(+ optional BVL supply)
        ↓
   epoch_root
        ↓
  mesh + optional OP_RETURN / CLI broadcast
```

Bitcoin does not store assets. It anchors *that the swarm committed to this root at this time*.
