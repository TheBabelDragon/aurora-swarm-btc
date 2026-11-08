# Conflux Deployment Contract (v0.1.1)

## Adapters

- `DryRunDeploymentAdapter` (default) — records intent, applies no host/remote changes
- Local adapter requires `CONFLUX_LOCAL_DEPLOY_ENABLED=1`

## Rules

- No automatic deploy to Aurora infrastructure
- No arbitrary remote shell
- Execute requires authorization capability `conflux:deployment:execute`
- Rollback references a previously recorded release via `rollback_release_id`

## Outcomes

Status includes `dry_run`, `succeeded`, `failed`, `rolled_back`. Accepted plan ≠ successful deploy.
