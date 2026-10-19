# Vendored third-party packages

## MultiFlow

**Upstream:** https://github.com/TheBabelDragon/MultiFlow  
**License:** MIT (see `MULTIFLOW_LICENSE`)  
**Version snapshot:** 0.2.0 (classical solver path; optional CP-SAT/MILP extras not bundled)

### Why vendor?

MultiFlow is a **separate product** with its own CI, versioning, and optional solver backends. Aurora previously treated it as an external install only, which left the adapter always `package_missing` in a default solo image.

Vendoring the **classical core** under `vendor/multiflow` means:

1. `import multiflow` works offline without a second clone.
2. Aurora still **feature-flags** use (`AURORA_MULTIFLOW_ENABLED`, default off).
3. Upstream remains the source of truth — refresh by copying `src/multiflow` from the MultiFlow repo.

Optional solvers (OR-Tools, PuLP) are **not** vendored. Install upstream extras if needed:

```bash
pip install "multiflow[cp-sat,milp] @ git+https://github.com/TheBabelDragon/MultiFlow.git"
```

Refresh snapshot:

```bash
git clone --depth 1 https://github.com/TheBabelDragon/MultiFlow.git /tmp/MultiFlow
rm -rf vendor/multiflow
cp -a /tmp/MultiFlow/src/multiflow vendor/multiflow
```
