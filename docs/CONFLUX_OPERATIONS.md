# Conflux Operations (v0.1.1)

## Mount

Conflux is mounted during dashboard boot via `dashboard/mount_all.py` → `dashboard/conflux_ops.py`.

- Singleton: `get_conflux_service()`
- Routes: `/conflux/*`
- Mount health: `GET /conflux-mount/status`
- Control plane entity: `aurora.conflux`

If mount fails, logs contain the error; status endpoint reports `mounted: false`. Do not assume operational from import alone.

## Health checks

```bash
curl -s http://127.0.0.1:8000/conflux/status | python -m json.tool
curl -s http://127.0.0.1:8000/conflux-mount/status | python -m json.tool
curl -s http://127.0.0.1:8000/control/entities | python -m json.tool | grep -A2 conflux
```

## Feature flags

| Env | Default | Meaning |
|-----|---------|--------|
| `CONFLUX_REQUIRE_AEGIS` | `1` | Fail closed without AEGIS |
| `CONFLUX_RUNNER_ENABLED` | `0` | Allow SafeTestRunner execution |
| `CONFLUX_LOCAL_DEPLOY_ENABLED` | `0` | Allow non-dry-run local targets |
| `AURORA_DASHBOARD_API_KEY` | unset | Protect mutations |

## Single-node path

1. Start Aurora solo dashboard.
2. Provision operator (see CONFLUX_SECURITY.md).
3. `POST /conflux/projects` with `X-Actor-Id`.
4. Add source, create changeset, build (skipped unless runner enabled), release, dry-run deploy.

## Evidence limitation

EvidenceStore is process-local. Export via EvidenceBridge for external durability.
