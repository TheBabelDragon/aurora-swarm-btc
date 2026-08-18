# Aurora Architecture (one page)

```text
                    AURORA SWARM
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    Control Plane   Data Plane    Settlement
          │              │              │
     registry        assets          BVL
     scheduler       pieces          LN (opt)
     thermal         manifests       epoch→BTC
     commands        RS / repair     mining events
          │              │              │
          └──────────────┼──────────────┘
                         │
                    CommsLayer
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
            Node A     Node B     Node C
```

## Data plane rule

> Never trust a node’s statement about data.  
> Trust independently verifiable content.

- **Claimed ≠ available** — only challenge/Merkle-verified possession counts  
- **Replication ≠ durability** — topology diversity + Reed–Solomon  
- **Bitcoin ≠ blob store** — timestamps epoch roots; does not host assets  
- **Mining provenance ≠ hardware on-chain** — progressive evidence only  

## Key endpoints

| Concern | Endpoint |
|---------|----------|
| Who holds asset | `GET /fabric/who` |
| Repair | `POST /fabric/repair` |
| Reconstruct RS | `POST /fabric/reconstruct` |
| Epoch commit | `POST /fabric/epoch` |
| Mining who | `GET /mining/who?epoch=` |
| Mining provenance | `GET /mining/provenance/<txid>` |
| BVL status | `GET /bvl/status` |

## Mod promotion path

Experiment in `mods/` → stabilize → promote durable abstraction to core.  
See `mods/README.md` and `docs/PROBLEMS_SOLVED.md`.
