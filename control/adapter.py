"""Shared adapter contract for Aurora ecosystem integrations.

Adapters declare identity, capabilities, operations, health reporting,
schemas, authorization, timeouts, and failure semantics.

Transport is replaceable. Adapters must not import sibling-project
internals or assume HTTP/Redis/common language.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .registry import Capability, CapabilityStatus, EntityType


ADAPTER_SCHEMA_ID = "aurora.ecosystem.adapter"
ADAPTER_SCHEMA_VERSION = "0.1.0"


class ActionSensitivity(str, Enum):
    ADVISORY = "advisory"
    REVERSIBLE = "reversible"
    SAFETY_SENSITIVE = "safety_sensitive"


class ActionOutcome(str, Enum):
    REQUESTED = "requested"
    AUTHORIZED = "authorized"
    DENIED = "denied"
    ACCEPTED = "accepted"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNKNOWN = "unknown"


@dataclass
class ActionDescriptor:
    """Description of one action an adapter can perform."""

    name: str
    sensitivity: ActionSensitivity = ActionSensitivity.ADVISORY
    request_schema: Dict[str, Any] = field(default_factory=dict)
    response_schema: Dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 30.0
    idempotent: bool = False
    authorization_scopes: List[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "sensitivity": self.sensitivity.value if isinstance(self.sensitivity, ActionSensitivity) else str(self.sensitivity),
            "request_schema": dict(self.request_schema),
            "response_schema": dict(self.response_schema),
            "timeout_s": self.timeout_s,
            "idempotent": self.idempotent,
            "authorization_scopes": list(self.authorization_scopes),
            "description": self.description,
        }


@dataclass
class AdapterManifest:
    """Static declaration published by an adapter."""

    adapter_id: str
    protocol_version: str = ADAPTER_SCHEMA_VERSION
    entity_type: EntityType = EntityType.SOFTWARE_SERVICE
    capabilities: List[Capability] = field(default_factory=list)
    read_operations: List[str] = field(default_factory=list)
    actions: List[ActionDescriptor] = field(default_factory=list)
    authorization_requirements: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_id": ADAPTER_SCHEMA_ID,
            "schema_version": ADAPTER_SCHEMA_VERSION,
            "adapter_id": self.adapter_id,
            "protocol_version": self.protocol_version,
            "entity_type": self.entity_type.value if isinstance(self.entity_type, EntityType) else str(self.entity_type),
            "capabilities": [c.to_dict() for c in self.capabilities],
            "read_operations": list(self.read_operations),
            "actions": [a.to_dict() for a in self.actions],
            "authorization_requirements": list(self.authorization_requirements),
            "metadata": dict(self.metadata),
        }


@dataclass
class ActionRequest:
    """Versioned request to perform an action through an adapter."""

    action: str
    entity_id: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    idempotency_key: str = ""
    correlation_id: str = ""
    expires_at: Optional[float] = None
    requested_by: str = ""
    created_at: float = 0.0

    def __post_init__(self):
        if not self.request_id:
            self.request_id = str(uuid.uuid4())
        if not self.idempotency_key:
            self.idempotency_key = self.request_id
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "entity_id": self.entity_id,
            "parameters": dict(self.parameters),
            "request_id": self.request_id,
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "expires_at": self.expires_at,
            "requested_by": self.requested_by,
            "created_at": self.created_at,
        }


@dataclass
class ActionResult:
    """Explicit outcome of an action request."""

    request_id: str
    outcome: ActionOutcome
    entity_id: str = ""
    action: str = ""
    message: str = ""
    result: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    authorized: Optional[bool] = None
    completed_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "outcome": self.outcome.value if isinstance(self.outcome, ActionOutcome) else str(self.outcome),
            "entity_id": self.entity_id,
            "action": self.action,
            "message": self.message,
            "result": dict(self.result),
            "evidence_refs": list(self.evidence_refs),
            "authorized": self.authorized,
            "completed_at": self.completed_at,
        }


class EcosystemAdapter(ABC):
    """Abstract adapter interface for project integrations."""

    @abstractmethod
    def manifest(self) -> AdapterManifest:
        """Return the static adapter declaration."""

    @abstractmethod
    def health(self) -> Dict[str, Any]:
        """Return current health/status. Must not raise for soft failures."""

    def read(self, operation: str, *, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Perform a read-only operation. Override when supported."""
        raise NotImplementedError(f"read operation '{operation}' not supported")

    def execute(self, request: ActionRequest) -> ActionResult:
        """Execute an action. Override when supported.

        Must never claim success from transport delivery alone.
        """
        return ActionResult(
            request_id=request.request_id,
            outcome=ActionOutcome.DENIED,
            entity_id=request.entity_id,
            action=request.action,
            message="adapter does not implement execute",
            authorized=False,
        )


class NullAdapter(EcosystemAdapter):
    """Reference adapter: observation-only, no actions."""

    def __init__(self, adapter_id: str = "null", entity_type: EntityType = EntityType.SOFTWARE_SERVICE):
        self._adapter_id = adapter_id
        self._entity_type = entity_type

    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id=self._adapter_id,
            entity_type=self._entity_type,
            capabilities=[
                Capability(
                    name="observe",
                    status=CapabilityStatus.DECLARED,
                    operations=["health"],
                ),
            ],
            read_operations=["health"],
            actions=[],
            authorization_requirements=[],
            metadata={"role": "reference_null_adapter"},
        )

    def health(self) -> Dict[str, Any]:
        return {
            "adapter_id": self._adapter_id,
            "status": "ok",
            "mode": "observation_only",
            "timestamp": time.time(),
        }

    def read(self, operation: str, *, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if operation == "health":
            return self.health()
        raise NotImplementedError(f"read operation '{operation}' not supported by NullAdapter")
