# Conflux Source Contract (v0.1.1)

## Adapter interface

`SourceAdapter` defines: `inspect_branches`, `inspect_tags`, `resolve_revision`, `list_revisions`, `snapshot`, `integrity_check`.

Initial implementation: `GitSourceAdapter` — subprocess git, **read-only**. No history rewrite, no force-push, no overwrite of existing repos.

## Identities

- `SourceRef.source_id` — content-derived from kind + remote + local path
- `SourceRevision.revision_id` — Git SHA when local repo available; synthetic hash for remote-only registration
- Snapshots capture tree identity without mutating source

## Future

Native Conflux source storage implements the same adapter contract without changing project/build/release/deployment APIs.
