# AEGIS-42 — Aurora Security Oversight

**Status:** Implemented on branch `feat/aegis-42-security-oversight`  
**Scope:** First-class, local-first security oversight integrated into Aurora node lifecycle.

## What is implemented

AEGIS-42 monitors Aurora’s own workers, tool invocations, capability changes, auth failures, routing/egress decisions, and related observable events. It evaluates them with a **deterministic policy engine** that does not require any AI model or network connection.

AI / local-model adapters are optional and **advisory only**. They cannot grant privileges, modify policy, erase audit records, or execute unrestricted containment.

### Package layout

```
mods/aegis_42/
  __init__.py
  core.py          # lifecycle, event queue, orchestration
  events.py        # normalized SecurityEvent model
  policy.py        # deterministic PolicyEngine + default rules
  identity.py      # IdentityRegistry, capabilities, trust, revocation
  audit.py         # append-only hash-chained AuditLog
  containment.py   # narrowly scoped authorized actions
  watchdog.py      # supervised watchdog + optional local adapters
  diagnostics.py   # metrics
  routes.py        # /aegis/* dashboard API
```

### Lifecycle integration

- Started automatically from `dashboard/boot_ops.py` during node boot (`_init_aegis`).
- Controlled by env `AEGIS_ENABLED` (default on; set `0`/`false`/`off` to disable).
- Graceful start/stop; bounded event queue (1000) with drop-on-saturation.
- Routes mounted at `/aegis/status`, `/aegis/events`, `/aegis/audit`, `/aegis/identities`, `/aegis/containment`.
- Reuses `AURORA_DASHBOARD_API_KEY` when set.

### Monitoring coverage (observable by Aurora today)

| Source | Events |
|--------|--------|
| Worker lifecycle | created, terminated, unexpected restart |
| Tool / job | tool invocation, job start/complete |
| Identity | capability change, forged identity, trust transition |
| Auth | authentication / authorization failures |
| Routing | route selection, gateway change, egress decision |
| Oversight | watchdog health, bypass attempt, integrity failure |
| Abuse | malformed / suspicious request, replay, queue saturation |

AEGIS does **not** claim visibility into host processes, model internals, or network traffic outside Aurora’s own interfaces.

### Deterministic enforcement

- Explicit policy rules with documented outcomes (`allow`, `deny`, `quarantine`, `rate_limit`, …).
- Default-deny for protected actions (unauthorized tools, privilege escalation, watchdog bypass, forged identity, replay).
- Scoped, revocable capabilities.
- Fail-closed when authorization cannot be established.
- Safe degradation for non-critical monitoring failures; never silently disables a security boundary to keep a worker running.
- Containment limited to: revoke capability, revoke identity, pause/quarantine worker, rate-limit actor, reject route, log-only.

### Trust model (roles)

| Role | Purpose |
|------|---------|
| SENTINEL | Behavioral anomaly detection (advisory when model-backed) |
| INQUEST | Evidence correlation / incident reconstruction |
| QUARANTINE | Policy-authorized containment |
| CONCLAVE | Independent review / trust evaluation |

Initial operation does **not** require 42 models, cloud inference, or external API keys. 42 is the long-term target for distinct verification responsibilities, not an assumption of identical-model consensus.

### Local-first

- No automatic upload of prompts, model outputs, credentials, or user data.
- Secrets redacted in events and logs.
- Model adapters can be fully disabled without disabling baseline policy.

## Threat model (explicit non-goals)

**In scope:** Aurora-observable agent/worker misbehavior, capability abuse, replay, audit tampering detection, unauthorized containment requests.

**Out of scope (v0):** Hardware isolation guarantees, full host process monitoring, network-wide kill switches, arbitrary remote shell, treating untrusted peer threat assertions as local authority, automatic destructive actions from model disagreement or false alarms.

## Operator usage

```bash
# Status
curl -s http://127.0.0.1:8000/aegis/status | python -m json.tool

# Recent policy decisions
curl -s http://127.0.0.1:8000/aegis/events | python -m json.tool

# Audit + integrity
curl -s http://127.0.0.1:8000/aegis/audit | python -m json.tool
```

Disable: `AEGIS_ENABLED=0`.

## Tests

```bash
python -m pytest tests/test_aegis_42.py -q
```

Includes: normal lifecycle, unauthorized tool, privilege escalation, forged identity, replay, tampered audit, watchdog crash, malicious watchdog output, bypass attempt, unauthorized containment, secret redaction, **compromised-worker scenario with all models off**, start/stop, env disable.

## Acceptance criteria (this branch)

1. AEGIS starts/stops through Aurora node lifecycle — **yes** (`boot_ops._init_aegis`).
2. Native workers / security events reach oversight through real interfaces — **yes** (convenience producers + ingest).
3. Deterministic policy works without AI or network — **yes**.
4. Simulated compromised worker detected and handled within policy — **yes** (test).
5. Verifiable evidence and explainable decisions — **yes** (audit chain + decision records).
6. Untrusted agents cannot self-grant privileges or disable oversight — **yes**.
7. Explicit failure behavior for monitoring / auth / containment — **yes**.
8. Existing routing / gateway / worker paths remain compatible — **yes** (additive integration).
9. Tests pass — run `pytest tests/test_aegis_42.py`.
10. Documentation matches implementation — **this file**.
11. All work on `feat/aegis-42-security-oversight`; main unchanged — **yes**.

## Roadmap (not implemented)

- Distributed peer threat intelligence with authenticated, expiring, revocable attestations.
- Additional independent evaluator implementations for CONCLAVE-scale diversity.
- Deeper hooks into every routing delivery path (current integration is event-level).
- Persistent on-disk audit store beyond in-memory chain (v0 is process-local).
- Full dashboard HTML panel (API is present; UI can consume `/aegis/*`).

## Pitch framing (for later)

Position as **independent security oversight for autonomous AI systems**, not anti-AI. Local models and tool-using agents need oversight that does not depend entirely on the model provider being monitored. Evidence from this branch: model-independent baseline, reproducible adversarial tests, verifiable incident records, demonstrated containment boundaries, local-first deployment.
