"""Aurora Mesh — distributed evidence integrity (Shared Evidence Contract Phase 6).

CONTENT hash = identity. HISTORY is append-only. Replication never rewrites
prior evidence objects. Upstream links to CANtheon / MetaField / TensorGate /
MultiFlow are plain dict refs — this module does not import those packages.
"""

from .envelope import (
    EvidenceObject,
    IntegrityStatus,
    content_hash,
    build_evidence_object,
    verify_integrity,
    check_schema,
)
from .store import EvidenceStore, ReplicationResult

__all__ = [
    "EvidenceObject",
    "IntegrityStatus",
    "content_hash",
    "build_evidence_object",
    "verify_integrity",
    "check_schema",
    "EvidenceStore",
    "ReplicationResult",
]
