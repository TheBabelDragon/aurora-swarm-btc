"""Conflux configuration.

All execution of untrusted code is disabled by default.
Runner, deployment, and remote shell paths require explicit enablement.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class ConfluxConfig:
    """Runtime configuration for Conflux.

    Safety defaults:
    - Build runners are disabled unless CONFLUX_RUNNER_ENABLED=1
    - Only the dry-run deployment adapter is active by default
    - Local deployment targets must be explicitly listed
    """

    # Feature flags
    runner_enabled: bool = field(default_factory=lambda: _bool_env("CONFLUX_RUNNER_ENABLED", False))
    local_deploy_enabled: bool = field(default_factory=lambda: _bool_env("CONFLUX_LOCAL_DEPLOY_ENABLED", False))
    require_aegis: bool = field(default_factory=lambda: _bool_env("CONFLUX_REQUIRE_AEGIS", True))

    # Persistence
    storage_backend: str = field(default_factory=lambda: os.getenv("CONFLUX_STORAGE", "memory"))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))

    # Limits
    max_changeset_files: int = 500
    max_projects: int = 200
    max_page_size: int = 100
    default_page_size: int = 20

    # Allowed local deploy targets (empty = none)
    allowed_local_targets: List[str] = field(default_factory=list)

    # Identity
    node_id: str = field(default_factory=lambda: os.getenv("AURORA_NODE_ID", "conflux-local"))

    @classmethod
    def from_env(cls) -> "ConfluxConfig":
        targets_raw = os.getenv("CONFLUX_ALLOWED_LOCAL_TARGETS", "")
        targets = [t.strip() for t in targets_raw.split(",") if t.strip()]
        return cls(allowed_local_targets=targets)
