# Conflux Architecture (v0.1)

Agent-native source control, artifact lifecycle, and deployment coordination for Aurora.

## Principle

**Git is a supported source-control protocol, not Conflux’s permanent architectural foundation.**

Source adapters are replaceable. Project, build, release, and deployment interfaces do not depend on Git internals.

## Subsystem boundaries

| Existing Aurora capability | Conflux responsibility |
|----------------------------|------------------------|
| CommsLayer | Node communication (future mesh ops) |
| Destination Routing | Locate services/nodes |
| Asset Fabric | Immutable software artifact lifecycle |
| Torrent Protocol | Large artifact distribution via Fabric |
| BTC Anchor | Optional temporal attestation |
| Evidence Integrity | Verifiable build/release evidence |
| AEGIS-42 | Authorization, audit, containment |
| Ecosystem Control Plane | Service registration |

Conflux **does not** duplicate these systems.

## Package layout

```
conflux/
  models/          # Project, Source, Changeset, Build, Artifact, Release, Deployment, Evidence
  source/          # SourceAdapter + GitSourceAdapter
  coordination/    # ChangesetCoordinator (conflict detection, approval)
  build/           # BuildRunner interface + SafeTestRunner
  deployment/      # DeploymentAdapter + DryRunDeploymentAdapter
  storage/         # ConfluxStore interface + MemoryStore
  routes.py        # /conflux/* API
  service.py       # Orchestration
  config.py        # Feature flags (runners/deploy off by default)
```

## Lifecycle

```
Project → Source (Git adapter) → Revision
       → Changeset (parallel, agent-native)
       → Reconcile (explicit; no silent semantic merge)
       → Approve
       → BuildManifest → BuildRecord (restricted runner)
       → ArtifactRef (content-addressed; Fabric publication in later integration)
       → Release (immutable)
       → Promote
       → DeploymentPlan → Dry-run Deployment
       → Provenance / Audit
```

## Safety defaults (v0.1)

- `CONFLUX_RUNNER_ENABLED` default **false** — no arbitrary code execution
- Only **SafeTestRunner** (synthetic artifacts, no subprocess/network)
- Deployment adapter default **dry_run**
- Local deploy requires explicit enable + allow-list
- Mutations respect `AURORA_DASHBOARD_API_KEY` when set
- Redis is not the sole permanent history authority

## Non-goals (v0.1)

- Replace Git internals
- New blockchain
- Mandatory Bitcoin for source/build/release
- Parallel torrent implementation
- General-purpose container runtime
- Unrestricted remote deployment
- Changes to mining / wallet / pool behavior

## API

Mounted at `/conflux/*`. See `conflux/routes.py`.

Key verbs: projects, sources, changesets (reconcile/approve), builds, artifacts, releases (promote), deployments (plan/execute/rollback), audit.

## Tests

```bash
python -m pytest tests/test_conflux.py -q
```

## v0.2 directions

- Full Asset Fabric publication path
- Evidence Integrity bridge for every build/release
- AEGIS-42 capability checks on every mutation
- Control-plane service registration
- Dashboard Conflux panel
- Production sandbox runner (still isolated)
- Native source adapter prototype
