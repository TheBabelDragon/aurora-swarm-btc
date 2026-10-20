"""Aurora Ecosystem Control Plane.

Provides capability registry, adapter contracts, desired/observed state,
and a coordination facade. Individual projects retain their execution
loops, domain logic, and local safety constraints.
"""

from .registry import (
    REGISTRY_SCHEMA_ID,
    REGISTRY_SCHEMA_VERSION,
    Capability,
    CapabilityRegistry,
    CapabilityStatus,
    EntityRegistration,
    EntityType,
    OperationalState,
    compute_registration_hash,
)
from .adapter import (
    ADAPTER_SCHEMA_ID,
    ADAPTER_SCHEMA_VERSION,
    ActionDescriptor,
    ActionOutcome,
    ActionRequest,
    ActionResult,
    ActionSensitivity,
    AdapterManifest,
    EcosystemAdapter,
    NullAdapter,
)
from .state import (
    DesiredState,
    EffectiveState,
    ObservedState,
    StateKind,
    StateStore,
)
from .plane import CONTROL_PLANE_VERSION, ControlPlane, ControlPlaneConfig

__all__ = [
    "REGISTRY_SCHEMA_ID",
    "REGISTRY_SCHEMA_VERSION",
    "ADAPTER_SCHEMA_ID",
    "ADAPTER_SCHEMA_VERSION",
    "CONTROL_PLANE_VERSION",
    "Capability",
    "CapabilityRegistry",
    "CapabilityStatus",
    "EntityRegistration",
    "EntityType",
    "OperationalState",
    "compute_registration_hash",
    "ActionDescriptor",
    "ActionOutcome",
    "ActionRequest",
    "ActionResult",
    "ActionSensitivity",
    "AdapterManifest",
    "EcosystemAdapter",
    "NullAdapter",
    "DesiredState",
    "EffectiveState",
    "ObservedState",
    "StateKind",
    "StateStore",
    "ControlPlane",
    "ControlPlaneConfig",
]
