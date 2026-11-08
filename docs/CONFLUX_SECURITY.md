# Conflux Security Contract (v0.1.1)

## Authentication

1. **API key** — when `AURORA_DASHBOARD_API_KEY` is set, mutations require header `X-API-Key`.
2. **Actor identity** — mutations require `X-Actor-Id` (or body actor field) corresponding to an AEGIS-registered identity.

Reads (`GET`) are open by default (same convention as `/comms/status`).

## Authorization (AEGIS-42)

Capabilities (explicit grant required):

| Capability | Operation |
|------------|-----------|
| `conflux:project:create` | Create project |
| `conflux:source:add` | Register source |
| `conflux:changeset:create` | Create changeset |
| `conflux:changeset:reconcile` | Reconcile |
| `conflux:changeset:approve` | Approve |
| `conflux:build:create` | Create build |
| `conflux:release:create` | Create release |
| `conflux:release:promote` | Promote release |
| `conflux:deployment:plan` | Plan deployment |
| `conflux:deployment:execute` | Execute deployment |
| `conflux:deployment:rollback` | Rollback |
| `conflux:*` | Wildcard (must be explicitly granted) |

### Rules

- **Fail closed** when `CONFLUX_REQUIRE_AEGIS=1` (default) and AEGIS is unavailable/disabled.
- Actor must exist in AEGIS identity registry (not merely appear in a header).
- Revoked identities are denied.
- Capabilities are never auto-granted from untrusted request paths.
- Trusted status alone is insufficient without an explicit conflux capability.

### Operator provisioning

Bootstrap only (system / operator, never untrusted HTTP):

```python
from mods.aegis_42 import start_aegis, get_aegis
from conflux.security.authorization import provision_operator

start_aegis(node_id="dashboard")
result = provision_operator(
    "ops-alice",
    capabilities=None,  # all non-wildcard conflux caps
    granted_by="system",
    trust_level="operator",
)
assert result["ok"]
```

Or grant individually:

```python
aegis = get_aegis()
aegis.identity.register("ops-alice", kind="operator", trust_level="operator")
aegis.identity.grant_capability("ops-alice", "conflux:release:promote", granted_by="system")
```

Request example:

```bash
curl -X POST http://127.0.0.1:8000/conflux/projects \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: $AURORA_DASHBOARD_API_KEY' \
  -H 'X-Actor-Id: ops-alice' \
  -d '{"name":"demo","created_by":"ops-alice"}'
```

## Evidence

Lifecycle events may be recorded via `EvidenceBridge` into `mods.evidence_integrity.EvidenceStore`.

**Limitation:** EvidenceStore is **in-memory**. Do not treat evidence as durable across process restart without an external persistence adapter (`export()` / `import_store`).

## Deployment safety

- Default adapter: `dry_run`
- Local deploy requires `CONFLUX_LOCAL_DEPLOY_ENABLED=1`
- Runners require `CONFLUX_RUNNER_ENABLED=1`
- No remote shell, no privileged containers in v0.1.1
