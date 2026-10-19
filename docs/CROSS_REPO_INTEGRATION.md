# Cross-Repository API Contracts & Runtime Integration

**Branch:** `feat/cross-repo-api-runtime`

## Path

```
Physical observations → CANtheon → MetaField → TensorGate → MultiFlow → Aurora → authorized execution
```

Each stage may be omitted **explicitly**; missing stages must not be simulated as success.

## Ownership

| Domain | Repository | Contract |
|--------|------------|----------|
| CAN/CAN-FD boundary | CANtheon | `cantheon.metafield_boundary@0.3.0` |
| Field semantics | metafield | FieldObservation + evidence lineage |
| Tensor identity / lineage | TensorGate | `tensorgate.lineage` |
| Scheduling / constraints | MultiFlow | `multiflow.scheduling_api@1.0.0` |
| Mesh execution + evidence store | aurora-swarm-btc | `aurora.mesh.evidence` + AEGIS-42 |

## Aurora modules

- `mods/cross_repo/contracts.py` — JSON-compatible envelopes
- `mods/cross_repo/multiflow_client.py` — optional `SchedulingApi` client (`AURORA_MULTIFLOW_ENABLED`, default off)
- `mods/cross_repo/evidence_bridge.py` — DecisionEvidence → EvidenceStore (no authorization power)

## Interface kinds

| Interface | Kind |
|-----------|------|
| MultiFlow `SchedulingApi` | In-process Python |
| CANtheon metafield_boundary | Pure Python + JSON envelope |
| MetaField cantheon_boundary adapter | In-process Python |
| TensorGate ComputationalLineage | In-process Python |
| Aurora evidence integrity | In-process store (durability separate) |

No HTTP servers were added solely for API coverage.

## MultiFlow pin

Prefer a **verified commit** of MultiFlow (see CANtheon `config/chimera-compatibility.json`). Do not install arbitrary upstream HEAD in production images without pinning.

```bash
pip install "multiflow @ git+https://github.com/TheBabelDragon/MultiFlow.git@<verified-sha>"
export AURORA_MULTIFLOW_ENABLED=1
```

## Tests

```bash
python -m pytest tests/test_cross_repo_contracts.py tests/test_evidence_integrity.py -q
```

## Security

- Validated MultiFlow plans are **not** execution authorization.
- AEGIS-42 remains independent.
- Solver evidence cannot grant capabilities.

## Authoritative sibling docs

- CANtheon: boundary + chimera compatibility manifest
- MultiFlow: `multiflow.api` + DecisionEvidence
- MetaField: `adapters/cantheon_boundary.py`
- TensorGate: `tensorgate/lineage.py`
