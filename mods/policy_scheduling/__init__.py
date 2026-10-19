"""Aurora Policy & Scheduling Control Plane.

Integrates MultiFlow as a feature-flagged scheduling adapter, editable
policy drafts with dry-run simulation, and AEGIS-42 authorization for
activation/rollback. Baseline scheduler remains the fallback.

Activation mode defaults to shadow — no live execution change until
authorized activation of an immutable policy version.
"""

from .schema import (
    ActivationMode,
    INITIAL_DRAFT,
    PolicyDocument,
    PolicyStatus,
    RecoveryStrategy,
)
from .service import PolicyService, get_policy_service, start_policy_service
from .multiflow_adapter import MultiFlowAdapter, MultiFlowAvailability

__all__ = [
    "ActivationMode",
    "INITIAL_DRAFT",
    "PolicyDocument",
    "PolicyStatus",
    "RecoveryStrategy",
    "PolicyService",
    "get_policy_service",
    "start_policy_service",
    "MultiFlowAdapter",
    "MultiFlowAvailability",
]
