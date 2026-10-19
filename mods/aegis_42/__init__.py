"""AEGIS-42 — Aurora Security Oversight

First-class, locally operational security oversight subsystem.
Monitors Aurora agents, workers, jobs, routing, gateways, permissions,
and observable security events from node startup.

Deterministic policy evaluation works with every AI model disabled.
AI classifications are advisory only; they never grant privileges,
modify trusted policy, erase audit records, or execute unrestricted
containment.

Roles (future expansion toward 42 verification responsibilities):
  SENTINEL   — behavioral anomaly detection
  INQUEST    — evidence correlation / incident reconstruction
  QUARANTINE — policy-authorized containment
  CONCLAVE   — independent review / trust evaluation
"""

from .core import Aegis42, get_aegis, start_aegis, stop_aegis
from .events import SecurityEvent, EventType, EventSource
from .policy import PolicyEngine, PolicyDecision, DecisionOutcome
from .identity import IdentityRegistry, Capability, TrustRecord
from .audit import AuditLog, AuditRecord
from .containment import ContainmentAction, ContainmentResult
from .diagnostics import AegisDiagnostics

__all__ = [
    "Aegis42",
    "get_aegis",
    "start_aegis",
    "stop_aegis",
    "SecurityEvent",
    "EventType",
    "EventSource",
    "PolicyEngine",
    "PolicyDecision",
    "DecisionOutcome",
    "IdentityRegistry",
    "Capability",
    "TrustRecord",
    "AuditLog",
    "AuditRecord",
    "ContainmentAction",
    "ContainmentResult",
    "AegisDiagnostics",
]
