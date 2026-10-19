"""Normalized security events and explicit event-source adapters."""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    WORKER_CREATED = "worker.created"
    WORKER_TERMINATED = "worker.terminated"
    WORKER_RESTART = "worker.unexpected_restart"
    JOB_STARTED = "job.started"
    JOB_COMPLETED = "job.completed"
    TOOL_INVOCATION = "tool.invocation"
    CAPABILITY_CHANGE = "capability.change"
    PERMISSION_DENIED = "permission.denied"
    AUTH_FAILURE = "auth.failure"
    ROUTE_SELECTED = "route.selected"
    GATEWAY_CHANGE = "gateway.change"
    EGRESS_DECISION = "egress.decision"
    MALFORMED_REQUEST = "request.malformed"
    SUSPICIOUS_REQUEST = "request.suspicious"
    WATCHDOG_HEALTH = "watchdog.health"
    WATCHDOG_BYPASS_ATTEMPT = "watchdog.bypass_attempt"
    INTEGRITY_FAILURE = "integrity.failure"
    TRUST_TRANSITION = "trust.transition"
    IDENTITY_FORGED = "identity.forged"
    REPLAY_DETECTED = "replay.detected"
    CONTAINMENT_REQUEST = "containment.request"
    POLICY_VIOLATION = "policy.violation"
    QUEUE_SATURATION = "queue.saturation"
    CUSTOM = "custom"


class EventSource(str, Enum):
    COMMS_LAYER = "comms.layer"
    WORKER_LIFECYCLE = "worker.lifecycle"
    ROUTING = "routing"
    GATEWAY = "gateway"
    DASHBOARD = "dashboard"
    POLICY_ENGINE = "policy"
    WATCHDOG = "watchdog"
    IDENTITY = "identity"
    AUDIT = "audit"
    EXTERNAL_ADAPTER = "external"
    TEST = "test"


class SecurityEvent(BaseModel):
    """Normalized security event observed by AEGIS-42."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    source: EventSource
    ts: float = Field(default_factory=time.time)
    node_id: Optional[str] = None
    actor_id: Optional[str] = None  # worker / agent / peer that triggered
    target_id: Optional[str] = None
    severity: str = "info"  # info | low | medium | high | critical
    summary: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    redacted: bool = False

    def redact_secrets(self, secret_keys: Optional[List[str]] = None) -> "SecurityEvent":
        keys = set(secret_keys or [
            "password", "secret", "token", "api_key", "api-key",
            "authorization", "credential", "private_key", "redis_url",
        ])
        details = {}
        for k, v in self.details.items():
            if any(s in k.lower() for s in keys):
                details[k] = "[REDACTED]"
            else:
                details[k] = v
        return self.model_copy(update={"details": details, "redacted": True})


def make_event(
    event_type: EventType,
    source: EventSource,
    *,
    node_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    target_id: Optional[str] = None,
    severity: str = "info",
    summary: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> SecurityEvent:
    return SecurityEvent(
        event_type=event_type,
        source=source,
        node_id=node_id,
        actor_id=actor_id,
        target_id=target_id,
        severity=severity,
        summary=summary or event_type.value,
        details=details or {},
    )
