# Shared Evidence Contract — Aurora Mesh (Phase 6)

**Status:** Implemented in `mods/evidence_integrity` — distributed evidence integrity.

## Ownership

| Layer | Owns |
|-------|------|
| CANtheon / CANgate | physical transport evidence |
| MetaField | field semantics + EvidenceLineage |
| TensorGate | numerical / computational lineage |
| MultiFlow | decision / outcome evidence |
| **Aurora Mesh** | content-hash identity, integrity check, append-only replication |

## Rules

1. **Content hash = identity** — SHA-256 over canonical payload JSON.
2. **Never rewrite history** — corrections are new objects with `parent_hashes`.
3. **Replication is idempotent** — duplicate hashes accepted as duplicates, not mutations.
4. **Fail-closed** — hash mismatch and schema major mismatch reject the object.
5. **No upstream imports** — linked via plain `evidence_refs`.

## API

```python
from mods.evidence_integrity import (
    build_evidence_object, verify_integrity, EvidenceStore,
)

obj = build_evidence_object(
    {"kind": "decision", "outcome": "ADMITTED"},
    node_id="node-a",
    evidence_refs=[{"schema_id": "multiflow.decision_evidence", "event_id": "dec-1"}],
)
store = EvidenceStore()
store.append(obj)
result = store.replicate([obj])  # accepted / rejected / duplicates
```

## Verification

```bash
python -m pytest tests/test_evidence_integrity.py -q
```
