# Conflux Build Contract (v0.1.1)

## Manifest

`BuildManifest` is content-hashed over project, revision, changesets, instructions, toolchain, locks, environment, inputs, expected outputs.

## Runner

- Interface: `BuildRunner.execute(manifest, enabled=...)`
- Default: **disabled** (`CONFLUX_RUNNER_ENABLED=0`)
- `SafeTestRunner` produces synthetic content-addressed artifacts; no subprocess, no network, no host mounts
- Dashboard process must never run arbitrary repository code

## Record

`BuildRecord` tracks status (planned/queued/running/succeeded/failed/cancelled/skipped), outputs, verification results, evidence refs.
