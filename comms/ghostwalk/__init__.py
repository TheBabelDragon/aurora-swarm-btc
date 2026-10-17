"""Aurora Autonomic Fabric Phase 2 — Ghostwalk.

Observable, policy-governed mesh topology and trust system.
Discovers actual mesh state, detects anomalies with evidence,
and proposes bounded recovery actions.

Concepts kept distinct:
  identity | authentication | authorization | reachability | reputation
"""

from .identity import (
    AuthResult,
    IdentityState,
    PeerRecord,
    TrustDecision,
    TrustPolicy,
    TrustPolicyEngine,
)
from .topology import (
    Observation,
    ObservationKind,
    ObservationSource,
    TopologyEngine,
    TopologySnapshot,
)
from .anomalies import AnomalyEngine, AnomalyFinding, FindingStatus, Severity
from .evidence import GhostwalkEvidence, evidence_persistence_status
from .recovery import RecoveryEngine, RecoveryProposal, ProposalStatus
from .service import GhostwalkService, get_ghostwalk, init_ghostwalk

__all__ = [
    "AuthResult",
    "IdentityState",
    "PeerRecord",
    "TrustDecision",
    "TrustPolicy",
    "TrustPolicyEngine",
    "Observation",
    "ObservationKind",
    "ObservationSource",
    "TopologyEngine",
    "TopologySnapshot",
    "AnomalyEngine",
    "AnomalyFinding",
    "FindingStatus",
    "Severity",
    "GhostwalkEvidence",
    "evidence_persistence_status",
    "RecoveryEngine",
    "RecoveryProposal",
    "ProposalStatus",
    "GhostwalkService",
    "get_ghostwalk",
    "init_ghostwalk",
]
