# Ghostwalk — Aurora Autonomic Fabric Phase 2

Observable, policy-governed mesh topology and trust for the configured Aurora mesh.

Ghostwalk answers:

- Which nodes exist, and what evidence supports their identity?
- Which peers are reachable, and through which observed paths?
- What changed, when, and with what evidence?
- Is an observation confirmed, stale, contradictory, or unknown?
- What recovery action is *proposed*, and what authorization does it need?

## Architecture

```
Discovery / CommsLayer peers
        │
        ▼
TrustPolicyEngine  ←── identity ≠ authentication ≠ trust ≠ reachability
        │
TopologyEngine     ←── time-aware observations + provenance
        │
AnomalyEngine      ←── deterministic rules; severity ⊥ confidence
        │
EvidenceRecorder   ←── mods/evidence_integrity (content-hash identity)
        │
RecoveryEngine     ←── proposals only (not auto-execution)
        │
Dashboard /ghostwalk/*
```

Does **not** replace Redis mesh, UDP discovery, destination routing, or Phase 1 delivery states.

## Peer identity vs authentication vs trust

| Concept | Meaning |
|---------|--------|
| Identity | Stable `node_id` + optional fingerprint |
| Authentication | Proof of mesh secret (or explicit unsigned) via existing `beacon_auth` |
| Trust | Policy decision: allow / defer / deny / quarantine |
| Reachability | Topology / delivery outcomes |
| Reputation | Not scored in v0.1; avoid silent privilege elevation |

Authenticated discovery proves possession of `AURORA_MESH_SECRET` when configured. It does **not** prove that capability claims are true.

## Observation freshness

- Each observation has `ts`, `expires_at`, `source` (`direct` \| `peer_advertised` \| `local`).
- Stale records remain queryable in timeline/history windows; they are not silently treated as malice.
- Bounded memory: timeline and per-subject observation lists are capped.

## Anomaly rules (v1)

| Rule ID | Intent |
|---------|--------|
| `peer_stale` | Known peer no longer fresh |
| `identity_conflict` | Fingerprint mismatch |
| `auth_failure` | Bad or required auth failed |
| `gateway_capability_change` | Unexpected gateway transports/caps |
| `delivery_failures` | Consecutive failures ≥ threshold |
| `policy_endpoint_violation` | Endpoint outside policy |
| `conflicting_observations` | Inconsistent multi-peer views |

Findings always include alternatives and `is_attack_claim: false`. Detection is not an attack verdict.

## Evidence

Receipts use `mods/evidence_integrity` when a store is configured:

- Canonical JSON → content hash = payload identity
- Secrets redacted (`AURORA_MESH_SECRET`, Redis URLs, tokens, signatures)
- `persistence_status`: `durable` or `memory_only` (+ error if any)

A content hash is **not** proof of authorship.

## Recovery proposals

Supported proposal actions (not auto-executed):

- `mark_degraded`
- `recommend_route_failover`
- `quarantine_peer`
- `revoke_peer` / credential rotation recommendations
- `operator_investigation`

Disruptive actions require explicit authorization (`operator`, `local_operator_only`). Peers cannot rewrite their own or others’ trust state through unauthenticated observations.

Public egress / relay remains out of scope (unchanged from destination routing).

## Local multi-node demonstration

```python
from mods.evidence_integrity import EvidenceStore
from comms.ghostwalk import GhostwalkService

store = EvidenceStore()
svc = GhostwalkService(local_node_id="node-a", evidence_store=store)
svc.observe_peer_advertisement("node-b", fingerprint="fpb", auth_ok=True, auth_reason="secret")
svc.observe_peer_advertisement("node-c", fingerprint="fpc", auth_ok=True, auth_reason="secret")
lost = svc.observe_peer_lost("node-b", last_seen=__import__("time").time() - 120)
print(lost["finding"]["rule_id"], lost["proposal"]["action"], lost["proposal"]["is_executed"])
svc.observe_peer_advertisement("node-b", fingerprint="fpb", auth_ok=True, auth_reason="secret")
svc.anomalies.resolve(lost["finding"]["finding_id"], reason="returned")
print(svc.status()["peer_counts"])
```

Or run tests:

```bash
python -m pytest tests/test_ghostwalk.py tests/test_autonomic_fabric_phase1.py tests/test_evidence_integrity.py -q
```

## Dashboard

| Endpoint | Notes |
|----------|--------|
| `GET /ghostwalk/status` | Counts, topology, open findings, proposals, evidence |
| `GET /ghostwalk/topology` | Snapshot |
| `GET /ghostwalk/findings` | Anomalies |
| `GET /ghostwalk/proposals` | Recovery proposals |
| `GET /ghostwalk/evidence` | Recent receipts |
| `GET /ghostwalk/timeline` | Observation timeline |
| `POST /ghostwalk/findings/{id}/ack` | Auth when API key set |
| `POST /ghostwalk/findings/{id}/resolve` | Auth when API key set |

## Security boundaries

- No unrestricted scanning; scope is configured mesh only
- No public egress or proxy in this phase
- No automatic credential wipe or peer deletion on heuristic score
- Dashboard mutations honor `AURORA_DASHBOARD_API_KEY`
- Compatible with `AURORA_MESH_SECRET` / `AURORA_MESH_REQUIRE_AUTH`

## Known limitations

- In-process topology (not a distributed consensus log)
- Evidence store defaults to in-memory unless wired to a durable backend
- Capability advertisements are claims, not verified endpoints
- No offensive or autonomous network mutation

## Extending

1. New observation source → `TopologyEngine.ingest(...)` with explicit `ObservationSource`
2. New anomaly rule → method on `AnomalyEngine` + tests with alternatives and non-attack framing
3. New recovery action → `RecoveryEngine.propose` with authorization + rollback text
