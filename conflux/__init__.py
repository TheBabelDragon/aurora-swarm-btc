"""Conflux — Aurora-native software lifecycle and deployment coordination.

v0.1: Git-compatible source adapter, agent changesets, deterministic build
records, Asset Fabric artifacts, immutable releases, dry-run deployments,
AEGIS-42 authorization, and evidence integrity.

Git is a supported source-control protocol, not the permanent architectural
foundation. Source adapters are replaceable without changing project, build,
release, or deployment interfaces.
"""

from __future__ import annotations

__version__ = "0.1.0"
__schema_id__ = "aurora.conflux"

from conflux.service import ConfluxService

__all__ = ["ConfluxService", "__version__", "__schema_id__"]
