# Policy & Scheduling Control Plane + MultiFlow

**Branch:** `feat/aurora-policy-scheduling-multiflow`  
**MultiFlow upstream:** https://github.com/TheBabelDragon/MultiFlow  
**Security:** `mods/aegis_42`

## Why MultiFlow was not (fully) inlined initially

MultiFlow is a **separate product**: own CI, versioning, optional CP-SAT/MILP extras, and a public demo. Copying the entire tree into Aurora would freeze a fork that drifts from upstream and bloated the mining image with solver deps operators may never enable.

**What we do instead:**

1. **Docker build** installs `multiflow` from upstream git (soft-fail if offline).
2. **`vendor/`** path + `scripts/ensure_multiflow_vendor.sh` for offline classical core.
3. **`requirements-multiflow.txt`** for host/venv installs.
4. Feature flag **`AURORA_MULTIFLOW_ENABLED`** (default **off**) so baseline scheduler stays safe.

```bash
# Host / CI
pip install -r requirements-multiflow.txt
# or offline snapshot
./scripts/ensure_multiflow_vendor.sh
export PYTHONPATH="$PWD/vendor:${PYTHONPATH:-}"
export AURORA_MULTIFLOW_ENABLED=1
```

## What this is

- Editable **policy drafts** (preferences, not hard constraints)
- **Dry-run simulation** and plan diffs
- Explicit **activation** with AEGIS-42 authorization
- **Redis-durable** versions, active reference, and audit when CommsLayer/Redis is up
- Baseline **Aurora scheduler** remains the fallback

Initial preview values (unsaved — **not** active):

```json
{
  "latency_preference": 65,
  "load_balancing_preference": 75,
  "energy_efficiency_preference": 30,
  "recovery_strategy": "balanced",
  "activation_mode": "shadow"
}
```

## Preferences vs hard constraints

| Preferences (0–100) | Hard constraints (not overridable by UI) |
|---------------------|------------------------------------------|
| Latency ranking weight | Worker availability / health |
| Load-balancing ranking | Measured capacity |
| Energy-efficiency ranking | AEGIS quarantine / revocation |
| Recovery strategy enum | Route eligibility / security policy |
| Activation mode | State freshness, retry budgets |

## State machine

```
DRAFT → SIMULATED → VALIDATED → PENDING_APPROVAL → ACTIVE
```

- **Shadow:** record active policy for comparison; baseline scheduler still executes.
- **Approval:** requires explicit `approved=true` after validation.
- **Controlled:** same gates; intended for future execution hand-off (still requires AEGIS).

## Durability

When Redis is reachable via CommsLayer:

- Policy versions, active id, draft, and audit are mirrored under `aurora:policy:*`
- On restart, `PolicyStore.attach_comms` reloads them (`durable_store: true` in `/policy/status`)
- Without Redis, behavior remains process-local (honest `durable_store: false`)

## API routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/policy/status` | Active, draft, preview, MultiFlow, durable_store |
| GET | `/policy/versions` | Immutable version list |
| GET | `/policy/audit` | Policy audit trail |
| POST | `/policy/preview` | Update unsaved preview |
| POST | `/policy/draft/save` | Save draft (not active) |
| POST | `/policy/draft/discard` | Discard draft |
| POST | `/policy/simulate` | Side-effect-free dry-run |
| POST | `/policy/validate` | Schema + simulation gate |
| POST | `/policy/activate` | Authorized activation |
| POST | `/policy/rollback` | New version from historical prefs |
| GET | `/policy/compare?a=&b=` | Preference diff |

## Tests

```bash
python -m pytest tests/test_policy_scheduling.py -q
```

## Remaining limitations

- Controlled mode does **not** yet replace the autonomous scheduler loop with MultiFlow dispatch.
- Optional solvers (OR-Tools, PuLP) are not installed by default.
- Full MultiFlow source tree is not permanently mirrored file-by-file; use the install/vendor paths above.
