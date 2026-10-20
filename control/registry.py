"""Ecosystem capability registry for the Aurora control plane.

Versioned, serializable registry of connected ecosystem entities.
Distinguishes declared capabilities from verified capabilities.
Does not infer identity from hostnames alone.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


REGISTRY_SCHEMA_ID = "aurora.ecosystem.registry"
REGISTRY_SCHEMA_VERSION = "0.1.0"

# Default staleness threshold (seconds) before a registration is marked stale
DEFAULT_STALE_AFTER_S = 120.0


class EntityType(str, Enum):
    PHYSICAL_DEVICE = "physical_device"
    EMBEDDED_NODE = "embedded_node"
    COMPUTE_BACKEND = "compute_backend"
    ACCELERATOR = "accelerator"
    SOFTWARE_SERVICE = "software_service"
    REPOSITORY_INTEGRATION = "repository_integration"
    VIEWER = "viewer"
    DASHBOARD = "dashboard"
    WORKLOAD = "workload"
    SCHEDULED_TASK = "scheduled_task"
    GATEWAY = "gateway"
    TRANSPORT_ENDPOINT = "transport_endpoint"
    UNKNOWN = "unknown"


class OperationalState(str, Enum):
    UNKNOWN = "unknown"
    REGISTERED = "registered"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    QUARANTINED = "quarantined"
    REVOKED = "revoked"


class CapabilityStatus(str, Enum):
    """Whether a capability is merely declared or has been verified."""
    DECLARED = "declared"
    VERIFIED = "verified"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class Capability:
    """A single capability offered by an entity."""

    name: str
    status: CapabilityStatus = CapabilityStatus.DECLARED
    operations: List[str] = field(default_factory=list)
    parameters_schema: Dict[str, Any] = field(default_factory=dict)
    safety_sensitive: bool = False
    last_verified_at: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value if isinstance(self.status, CapabilityStatus) else str(self.status),
            "operations": list(self.operations),
            "parameters_schema": dict(self.parameters_schema),
            "safety_sensitive": self.safety_sensitive,
            "last_verified_at": self.last_verified_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Capability":
        status_raw = str(d.get("status") or "declared").lower()
        try:
            status = CapabilityStatus(status_raw)
        except ValueError:
            status = CapabilityStatus.UNKNOWN
        return cls(
            name=str(d.get("name") or ""),
            status=status,
            operations=list(d.get("operations") or []),
            parameters_schema=dict(d.get("parameters_schema") or {}),
            safety_sensitive=bool(d.get("safety_sensitive", False)),
            last_verified_at=d.get("last_verified_at"),
            notes=str(d.get("notes") or ""),
        )


@dataclass
class EntityRegistration:
    """Registration record for one ecosystem entity."""

    entity_id: str
    entity_type: EntityType
    adapter_id: str
    protocol_version: str = "0.1.0"
    capabilities: List[Capability] = field(default_factory=list)
    health: str = "unknown"
    last_seen: float = 0.0
    execution_location: str = ""
    resource_constraints: Dict[str, Any] = field(default_factory=dict)
    operational_state: OperationalState = OperationalState.REGISTERED
    authorization_requirements: List[str] = field(default_factory=list)
    evidence_refs: List[Dict[str, Any]] = field(default_factory=list)
    registration_source: str = ""
    last_sync_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Content-addressed identity of the registration payload (stable fields only)
    content_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type.value if isinstance(self.entity_type, EntityType) else str(self.entity_type),
            "adapter_id": self.adapter_id,
            "protocol_version": self.protocol_version,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "health": self.health,
            "last_seen": self.last_seen,
            "execution_location": self.execution_location,
            "resource_constraints": dict(self.resource_constraints),
            "operational_state": (
                self.operational_state.value
                if isinstance(self.operational_state, OperationalState)
                else str(self.operational_state)
            ),
            "authorization_requirements": list(self.authorization_requirements),
            "evidence_refs": list(self.evidence_refs),
            "registration_source": self.registration_source,
            "last_sync_at": self.last_sync_at,
            "metadata": dict(self.metadata),
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EntityRegistration":
        et_raw = str(d.get("entity_type") or "unknown").lower()
        try:
            entity_type = EntityType(et_raw)
        except ValueError:
            entity_type = EntityType.UNKNOWN
        os_raw = str(d.get("operational_state") or "registered").lower()
        try:
            operational_state = OperationalState(os_raw)
        except ValueError:
            operational_state = OperationalState.UNKNOWN
        caps = [Capability.from_dict(c) for c in (d.get("capabilities") or []) if c]
        return cls(
            entity_id=str(d.get("entity_id") or ""),
            entity_type=entity_type,
            adapter_id=str(d.get("adapter_id") or ""),
            protocol_version=str(d.get("protocol_version") or "0.1.0"),
            capabilities=caps,
            health=str(d.get("health") or "unknown"),
            last_seen=float(d.get("last_seen") or 0.0),
            execution_location=str(d.get("execution_location") or ""),
            resource_constraints=dict(d.get("resource_constraints") or {}),
            operational_state=operational_state,
            authorization_requirements=list(d.get("authorization_requirements") or []),
            evidence_refs=list(d.get("evidence_refs") or []),
            registration_source=str(d.get("registration_source") or ""),
            last_sync_at=float(d.get("last_sync_at") or 0.0),
            metadata=dict(d.get("metadata") or {}),
            content_hash=str(d.get("content_hash") or ""),
        )


def _stable_hash(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compute_registration_hash(reg: EntityRegistration) -> str:
    """Content hash over identity-relevant fields only (not timestamps/health)."""
    payload = {
        "entity_id": reg.entity_id,
        "entity_type": reg.entity_type.value if isinstance(reg.entity_type, EntityType) else str(reg.entity_type),
        "adapter_id": reg.adapter_id,
        "protocol_version": reg.protocol_version,
        "capabilities": sorted(
            [
                {
                    "name": c.name,
                    "operations": sorted(c.operations),
                    "safety_sensitive": c.safety_sensitive,
                }
                for c in reg.capabilities
            ],
            key=lambda x: x["name"],
        ),
        "authorization_requirements": sorted(reg.authorization_requirements),
        "registration_source": reg.registration_source,
    }
    return _stable_hash(payload)


class CapabilityRegistry:
    """In-memory capability registry with staleness and lifecycle support.

    Designed to be backed by Redis or another store later; the in-memory
    form is sufficient for unit tests and single-node observation.
    """

    def __init__(self, *, stale_after_s: float = DEFAULT_STALE_AFTER_S):
        self._entities: Dict[str, EntityRegistration] = {}
        self.stale_after_s = stale_after_s
        self.schema_id = REGISTRY_SCHEMA_ID
        self.schema_version = REGISTRY_SCHEMA_VERSION

    def register(self, reg: EntityRegistration, *, now: Optional[float] = None) -> EntityRegistration:
        """Register or re-register an entity. Returns the stored record."""
        if not reg.entity_id:
            raise ValueError("entity_id is required")
        if not reg.adapter_id:
            raise ValueError("adapter_id is required")
        ts = now if now is not None else time.time()
        reg.last_seen = ts
        reg.last_sync_at = ts
        if reg.operational_state in (OperationalState.UNKNOWN, OperationalState.DISCONNECTED):
            reg.operational_state = OperationalState.REGISTERED
        reg.content_hash = compute_registration_hash(reg)
        self._entities[reg.entity_id] = reg
        return reg

    def unregister(self, entity_id: str) -> bool:
        return self._entities.pop(entity_id, None) is not None

    def heartbeat(
        self,
        entity_id: str,
        *,
        health: Optional[str] = None,
        now: Optional[float] = None,
    ) -> Optional[EntityRegistration]:
        reg = self._entities.get(entity_id)
        if reg is None:
            return None
        ts = now if now is not None else time.time()
        reg.last_seen = ts
        if health is not None:
            reg.health = health
        if reg.operational_state in (
            OperationalState.STALE,
            OperationalState.DISCONNECTED,
            OperationalState.REGISTERED,
        ):
            reg.operational_state = OperationalState.HEALTHY if (health or reg.health) not in ("degraded", "error") else OperationalState.DEGRADED
        return reg

    def get(self, entity_id: str) -> Optional[EntityRegistration]:
        return self._entities.get(entity_id)

    def list(
        self,
        *,
        entity_type: Optional[EntityType] = None,
        include_stale: bool = True,
        now: Optional[float] = None,
    ) -> List[EntityRegistration]:
        ts = now if now is not None else time.time()
        out: List[EntityRegistration] = []
        for reg in self._entities.values():
            self._refresh_staleness(reg, ts)
            if entity_type is not None and reg.entity_type != entity_type:
                continue
            if not include_stale and reg.operational_state in (
                OperationalState.STALE,
                OperationalState.DISCONNECTED,
            ):
                continue
            out.append(reg)
        out.sort(key=lambda r: r.entity_id)
        return out

    def mark_capability_verified(
        self,
        entity_id: str,
        capability_name: str,
        *,
        now: Optional[float] = None,
    ) -> bool:
        reg = self._entities.get(entity_id)
        if reg is None:
            return False
        ts = now if now is not None else time.time()
        for cap in reg.capabilities:
            if cap.name == capability_name:
                cap.status = CapabilityStatus.VERIFIED
                cap.last_verified_at = ts
                reg.content_hash = compute_registration_hash(reg)
                return True
        return False

    def mark_capability_failed(self, entity_id: str, capability_name: str) -> bool:
        reg = self._entities.get(entity_id)
        if reg is None:
            return False
        for cap in reg.capabilities:
            if cap.name == capability_name:
                cap.status = CapabilityStatus.FAILED
                reg.content_hash = compute_registration_hash(reg)
                return True
        return False

    def quarantine(self, entity_id: str) -> bool:
        reg = self._entities.get(entity_id)
        if reg is None:
            return False
        reg.operational_state = OperationalState.QUARANTINED
        return True

    def revoke(self, entity_id: str) -> bool:
        reg = self._entities.get(entity_id)
        if reg is None:
            return False
        reg.operational_state = OperationalState.REVOKED
        return True

    def _refresh_staleness(self, reg: EntityRegistration, now: float) -> None:
        if reg.operational_state in (
            OperationalState.QUARANTINED,
            OperationalState.REVOKED,
        ):
            return
        if reg.last_seen <= 0:
            return
        age = now - reg.last_seen
        if age > self.stale_after_s * 2:
            reg.operational_state = OperationalState.DISCONNECTED
            if reg.health == "unknown" or reg.health == "healthy":
                reg.health = "disconnected"
        elif age > self.stale_after_s:
            reg.operational_state = OperationalState.STALE
            if reg.health == "healthy":
                reg.health = "stale"

    def to_dict(self) -> dict:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "entities": [e.to_dict() for e in self.list()],
        }

    @classmethod
    def from_dict(cls, d: dict, *, stale_after_s: float = DEFAULT_STALE_AFTER_S) -> "CapabilityRegistry":
        reg = cls(stale_after_s=stale_after_s)
        for item in d.get("entities") or []:
            entity = EntityRegistration.from_dict(item)
            reg._entities[entity.entity_id] = entity
        return reg
