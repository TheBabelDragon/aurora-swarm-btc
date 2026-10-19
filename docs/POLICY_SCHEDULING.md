# Policy & Scheduling Control Plane + MultiFlow

**Branch:** `feat/aurora-policy-scheduling-multiflow`  
**MultiFlow:** https://github.com/TheBabelDragon/MultiFlow  
**Security:** `mods/aegis_42`

## What this is

A control surface for Aurora’s distributed operations:

- Editable **policy drafts** (preferences, not hard constraints)
- **Dry-run simulation** and plan diffs
- Explicit **activation** workflow with AEGIS-42 authorization
- **MultiFlow** as a feature-flagged scheduling adapter (disabled by default)
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

A preference may rank feasible plans differently. It may **never** make an unauthorized or infeasible plan admissible.

## State machine

```
DRAFT → SIMULATED → VALIDATED → PENDING_APPROVAL → ACTIVE
```

- **Shadow:** record active policy for comparison; baseline scheduler still executes.
- **Approval:** requires explicit `approved=true` after validation.
- **Controlled:** same gates; intended for future execution hand-off (still requires AEGIS).

Activation mode cannot disable AEGIS-42 or remove hard constraints.

## API routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/policy/status` | Active, draft, preview, MultiFlow availability |
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

Mutations respect `AURORA_DASHBOARD_API_KEY` when set.

## MultiFlow adapter

- Flag: `AURORA_MULTIFLOW_ENABLED` (default **off**)
- When off or package missing: truthful `availability` status; local ranking estimates only; **no** false “operational” claim
- When on and `multiflow` importable: uses `LiveEngine` + independent validator path
- Execution dispatch through MultiFlow remains gated; shadow is the safe default

Install MultiFlow separately if you want the real solver path:

```bash
pip install -e /path/to/MultiFlow
export AURORA_MULTIFLOW_ENABLED=1
```

## Operator walkthrough (shadow)

1. Open dashboard → **Policy & Scheduling Rules** panel.
2. Adjust sliders (preview only).
3. **Save draft** → confirm `active_unchanged`.
4. **Simulate** → inspect plan diff; `side_effect_free: true`.
5. **Validate** → check `validation_ok`.
6. **Request activation** → shadow records active version; live mining/scheduling path unchanged.
7. `/policy/audit` → verify history.
8. **Rollback** via API with a prior `version_id` if needed.

## AEGIS & audit limitations

- Activation/rollback go through AEGIS capability/trust checks when AEGIS is running.
- Policy audit is process-local (same class of durability as AEGIS v0 audit).
- Do not claim restart-safe durable audit until a persistent store is wired.

## Tests

```bash
python -m pytest tests/test_policy_scheduling.py -q
```
