"""Build runner interface.

IMPORTANT:
- Do not execute arbitrary repository code in the dashboard process.
- Do not expose host credentials.
- Do not allow unrestricted network.
- Do not mount sensitive host paths.
- Do not run privileged containers.
- Keep runner execution disabled unless explicitly configured.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from conflux.models.build import BuildManifest, BuildRecord, BuildStatus
from conflux.models.artifact import ArtifactRef


class BuildRunner(ABC):
    """Restricted runner contract."""

    @abstractmethod
    def execute(self, manifest: BuildManifest, *, enabled: bool = False) -> BuildRecord:
        ...


class SafeTestRunner(BuildRunner):
    """Deterministic test runner that never executes untrusted code.

    Produces a synthetic successful build record and content-hashed
    placeholder artifacts for pipeline testing only.
    """

    def execute(self, manifest: BuildManifest, *, enabled: bool = False) -> BuildRecord:
        record = BuildRecord.new(manifest.manifest_id, manifest.project_id)
        record.execution_id = "exec_" + uuid.uuid4().hex[:10]
        record.started_at = time.time()

        if not enabled:
            record.status = BuildStatus.SKIPPED
            record.error = "runner_disabled"
            record.finished_at = time.time()
            record.verification_results = {"runner": "disabled", "policy": "safe_default"}
            return record

        # Safe path: no subprocess, no network, no filesystem write outside memory
        outputs: List[str] = []
        for name in (manifest.expected_outputs or ["artifact.bin"]):
            payload = f"conflux-test:{manifest.content_hash}:{name}".encode()
            art = ArtifactRef.from_bytes(
                payload,
                name=name,
                project_id=manifest.project_id,
                build_id=record.build_id,
                source_revision_id=manifest.source_revision_id,
            )
            outputs.append(art.artifact_id)
            # Attach artifact dicts for downstream via metadata
            record.metadata.setdefault("artifacts", []).append(art.to_dict())

        record.output_artifact_ids = outputs
        record.status = BuildStatus.SUCCEEDED
        record.finished_at = time.time()
        record.verification_results = {
            "runner": "safe_test",
            "manifest_hash": manifest.content_hash,
            "output_count": len(outputs),
        }
        return record
