# Aurora Swarm BTC

Entropy-driven Bitcoin mining swarm with a Comms Layer mesh, sensing contract, and a growing hybrid path into MetaField.

**They yearn for the mines.**

## Layers

```
CONTENT     immutable artifact          (content hash = identity)
FABRIC      artifact lifecycle + possession
TORRENT     piece transport
BTC         scarce external temporal ordering
HISTORY     replicated artifact memory
EVIDENCE    integrity-checked evidence objects (mods/evidence_integrity)
```

## Shared Evidence Contract

Aurora Mesh evidence integrity (`mods/evidence_integrity`) provides content-hash
identity, integrity verification, and append-only replication for distributed
evidence objects. See `docs/SHARED_EVIDENCE_CONTRACT.md`.

```bash
python -m pytest tests/test_evidence_integrity.py -q
```

## Mesh

See `MESH.md` for multi-node Redis mesh, discovery, and destination routing.

## Integration

See `INTEGRATION_CONTRACT.md` for sensing ↔ swarm ↔ MetaField contracts.

## License

See repository license file.
