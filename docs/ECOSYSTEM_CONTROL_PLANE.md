# Aurora Ecosystem Control Plane

**Status:** Foundation implemented on `feat/ecosystem-control-plane` (v0.1.0)

Aurora is elevated from a mesh and distributed-compute subsystem into the
**control plane** for the wider BabelDragon ecosystem.

## Separation of concerns

| Layer | Owns | Does not own |
|-------|------|--------------|
| **Aurora control plane** | identity, capability registry, policy surface, desired/observed state, task placement metadata, health, cross-project coordination | domain execution loops, firmware, numerical kernels, physical interlocks |
| **TensorGate** | numerical contracts, portable kernels, quantization, computational lineage | device control, mesh transport |
| **BabelForge** | hardware toolchain / accelerator integration (when verified) | ecosystem policy |
| **CANtheon** | normalized physical observations and evidence | scheduling |
| **MetaField** | mathematical workloads and field semantics | mesh membership |
| **ESP32 firmware** | deterministic local execution, peripheral arbitration, hardware safety | remote shell |
| **Viewers** (EchoField, Throne Room, Work Bench, …) | specialized UI | authorization authority |

Aurora must not become a universal monolith or a runtime dependency of every firmware project.

## Architecture

```
Operator / Viewer / Policy
          │
          ▼
┌────────────────────────────────┐
│  Aurora Control Plane       │
│  - CapabilityRegistry       │
│  - Adapter contract         │
│  - Desired / Observed state │
│  - Action authorization     │
│  - Audit (no secrets)       │
└─────────────┬──────────────────────────────┘
              │ adapters (versioned)
     ┌────────┼────────┬──────────┐
     ▼        ▼        ▼          ▼
 TensorGate  Mesh   MetaField   Future
 (observe)  peers   bridge      ESP32/…
```

## Entity and capability contracts

See `control/registry.py`.

- Entity types: physical device, embedded node, compute backend, software service,
  viewer, workload, gateway, etc.
- Each registration has a stable `entity_id`, `adapter_id`, protocol version,
  capabilities, health, operational state, authorization requirements, and
  evidence refs.
- **Declared** capabilities are not **verified**. Verification requires successful
  execution evidence.
- Stale / disconnected states are explicit. Missing telemetry is not reported as healthy.

## Adapter contract

See `control/adapter.py`.

An adapter declares identity, read operations, actions (with sensitivity:
advisory / reversible / safety-sensitive), schemas, timeouts, and auth scopes.

- Transport is replaceable (mesh, gateway, serial bridge, …).
- Adapters must not import arbitrary sibling-project internals.
- Reference implementation: `NullAdapter` (observation only).
- Real adapters are added only when external interfaces are verified.

## Desired / observed / effective state

See `control/state.py`.

| Kind | Meaning |
|------|---------|
| Desired | What policy/operator requests |
| Observed | What the entity reports |
| Effective | Reconciliation result |

Outcomes are explicit: requested, authorized, denied, accepted, executing,
succeeded, failed, timed out, unknown.

Transport delivery is never treated as successful execution.
Non-idempotent physical actions must not be endlessly retried.

## Security (AEGIS-42 alignment)

- Actions require explicit authorization from the caller (AEGIS-42 / policy).
- Registration alone does not grant trust.
- Quarantine and revoke are supported at the registry level.
- Audit events never include credentials.
- Safety-sensitive physical operations remain subject to device-local interlocks.
- Loss of Aurora connectivity must not disable local safety behavior.

## Task placement

V0.1 provides registry + eligibility metadata hooks. The existing `scheduler/`
recovery path is not rewritten. Future work may match workload requirements
against declared capabilities; TensorGate remains the authority for tensor
operation semantics.

## Viewers as clients

Viewers discover authorized entities, read health/state/evidence, and request
permitted actions through Aurora. Displaying a device does not imply permission
to control it. Local viewer functionality may continue when Aurora is unavailable.

## Offline behavior

- Registry marks entities stale/disconnected when heartbeats lapse.
- Observation continues from last-known state with explicit confidence.
- Actions against disconnected or quarantined entities are denied.

## Staged integration path

1. **Now:** registry, adapter contract, desired/observed state, null + test adapters, unit tests.
2. **Next:** wire control-plane routes into the existing dashboard/API with AEGIS-42 checks.
3. **Later:** verified adapters for TensorGate observation, MetaField bridge status, mesh nodes.
4. **Only after conformance tests:** ESP32 or other physical action adapters.

## Testing

```bash
PYTHONPATH=. python -m pytest tests/test_ecosystem_control_plane.py -q
```

All tests use deterministic fake adapters. Simulated devices are never reported
as real connected hardware.

## Module map

```
control/
  __init__.py      # public exports
  registry.py      # CapabilityRegistry, EntityRegistration
  adapter.py       # EcosystemAdapter, NullAdapter, Action*
  state.py         # Desired / Observed / Effective
  plane.py         # ControlPlane facade
  bus.py           # existing Redis bus (unchanged)
```
