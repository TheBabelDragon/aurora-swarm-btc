"""Deterministic policy evaluation independent of any AI model.

Default-deny for protected actions where the security boundary permits it.
Fail-closed for authorization when identity cannot be established.
AI classifications are advisory inputs only.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from .events import SecurityEvent, EventType


class DecisionOutcome(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    QUARANTINE = "quarantine"
    RATE_LIMIT = "rate_limit"
    REQUIRE_REVIEW = "require_review"
    ADVISORY = "advisory"  # model suggestion only; does not change enforcement


class PolicyDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: f"pd-{time.time_ns()}")
    outcome: DecisionOutcome
    rule_id: str
    event_id: Optional[str] = None
    actor_id: Optional[str] = None
    reason: str = ""
    evidence: List[str] = Field(default_factory=list)
    ts: float = Field(default_factory=time.time)
    model_advisory: Optional[str] = None  # never authoritative


class PolicyRule(BaseModel):
    rule_id: str
    description: str
    event_types: Set[str] = Field(default_factory=set)
    severity_min: Optional[str] = None
    outcome: DecisionOutcome = DecisionOutcome.DENY
    protected: bool = True  # protected rules cannot be disabled by monitored agents
    enabled: bool = True


# Explicit default rules — model-independent baseline
DEFAULT_RULES: List[PolicyRule] = [
    PolicyRule(
        rule_id="deny-unauthorized-tool",
        description="Deny tool invocation without registered capability",
        event_types={EventType.TOOL_INVOCATION.value},
        outcome=DecisionOutcome.DENY,
        protected=True,
    ),
    PolicyRule(
        rule_id="deny-privilege-escalation",
        description="Deny capability changes that expand privileges without operator grant",
        event_types={EventType.CAPABILITY_CHANGE.value},
        outcome=DecisionOutcome.DENY,
        protected=True,
    ),
    PolicyRule(
        rule_id="quarantine-forged-identity",
        description="Quarantine on forged or invalid identity signatures",
        event_types={EventType.IDENTITY_FORGED.value},
        outcome=DecisionOutcome.QUARANTINE,
        protected=True,
    ),
    PolicyRule(
        rule_id="deny-replay",
        description="Deny replayed previously accepted events",
        event_types={EventType.REPLAY_DETECTED.value},
        outcome=DecisionOutcome.DENY,
        protected=True,
    ),
    PolicyRule(
        rule_id="deny-watchdog-bypass",
        description="Deny attempts to disable or bypass registered oversight",
        event_types={EventType.WATCHDOG_BYPASS_ATTEMPT.value},
        outcome=DecisionOutcome.DENY,
        protected=True,
    ),
    PolicyRule(
        rule_id="deny-unauthorized-containment",
        description="Deny containment requests not issued by authorized QUARANTINE role",
        event_types={EventType.CONTAINMENT_REQUEST.value},
        outcome=DecisionOutcome.DENY,
        protected=True,
    ),
    PolicyRule(
        rule_id="rate-limit-malformed",
        description="Rate-limit repeated malformed or unauthorized requests",
        event_types={EventType.MALFORMED_REQUEST.value, EventType.SUSPICIOUS_REQUEST.value},
        outcome=DecisionOutcome.RATE_LIMIT,
        protected=True,
    ),
    PolicyRule(
        rule_id="allow-normal-worker-lifecycle",
        description="Allow normal worker creation/termination",
        event_types={EventType.WORKER_CREATED.value, EventType.WORKER_TERMINATED.value},
        outcome=DecisionOutcome.ALLOW,
        protected=False,
    ),
]


class PolicyEngine:
    """Deterministic policy evaluation. No model required."""

    def __init__(self, rules: Optional[List[PolicyRule]] = None):
        self.rules: Dict[str, PolicyRule] = {}
        for r in (rules or DEFAULT_RULES):
            self.rules[r.rule_id] = r
        self._decisions: List[PolicyDecision] = []
        self._max_decisions = 500

    def evaluate(self, event: SecurityEvent, *,
                 actor_capabilities: Optional[Set[str]] = None,
                 actor_trusted: bool = False) -> PolicyDecision:
        """Evaluate event against explicit rules. Fail-closed for protected actions."""
        caps = actor_capabilities or set()
        matching = []
        for rule in self.rules.values():
            if not rule.enabled:
                continue
            if rule.event_types and event.event_type.value not in rule.event_types:
                continue
            matching.append(rule)

        if not matching:
            # Default: allow non-protected observability events; deny unknown protected
            if event.event_type in (
                EventType.WORKER_CREATED,
                EventType.WORKER_TERMINATED,
                EventType.JOB_STARTED,
                EventType.JOB_COMPLETED,
                EventType.ROUTE_SELECTED,
            ):
                decision = PolicyDecision(
                    outcome=DecisionOutcome.ALLOW,
                    rule_id="default-allow-observability",
                    event_id=event.event_id,
                    actor_id=event.actor_id,
                    reason="No matching restrictive rule; observability event allowed",
                )
            else:
                decision = PolicyDecision(
                    outcome=DecisionOutcome.DENY,
                    rule_id="default-deny",
                    event_id=event.event_id,
                    actor_id=event.actor_id,
                    reason="No matching allow rule; fail-closed",
                )
            self._record(decision)
            return decision

        # Prefer most restrictive matching rule
        priority = {
            DecisionOutcome.QUARANTINE: 0,
            DecisionOutcome.DENY: 1,
            DecisionOutcome.RATE_LIMIT: 2,
            DecisionOutcome.REQUIRE_REVIEW: 3,
            DecisionOutcome.ADVISORY: 4,
            DecisionOutcome.ALLOW: 5,
        }
        best = min(matching, key=lambda r: priority.get(r.outcome, 99))

        # Extra checks for capability-gated actions
        if event.event_type == EventType.TOOL_INVOCATION:
            tool = (event.details or {}).get("tool") or (event.details or {}).get("name")
            if tool and f"tool:{tool}" not in caps and "*" not in caps:
                decision = PolicyDecision(
                    outcome=DecisionOutcome.DENY,
                    rule_id="deny-unauthorized-tool",
                    event_id=event.event_id,
                    actor_id=event.actor_id,
                    reason=f"Actor lacks capability tool:{tool}",
                    evidence=[f"caps={sorted(caps)}"],
                )
                self._record(decision)
                return decision

        if event.event_type == EventType.CAPABILITY_CHANGE and not actor_trusted:
            decision = PolicyDecision(
                outcome=DecisionOutcome.DENY,
                rule_id="deny-privilege-escalation",
                event_id=event.event_id,
                actor_id=event.actor_id,
                reason="Untrusted actor cannot expand capabilities",
            )
            self._record(decision)
            return decision

        decision = PolicyDecision(
            outcome=best.outcome,
            rule_id=best.rule_id,
            event_id=event.event_id,
            actor_id=event.actor_id,
            reason=best.description,
            evidence=[f"matched_rule={best.rule_id}"],
        )
        self._record(decision)
        return decision

    def _record(self, decision: PolicyDecision) -> None:
        self._decisions.append(decision)
        if len(self._decisions) > self._max_decisions:
            self._decisions = self._decisions[-self._max_decisions:]

    def recent_decisions(self, limit: int = 50) -> List[PolicyDecision]:
        return list(reversed(self._decisions[-limit:]))

    def get_rule(self, rule_id: str) -> Optional[PolicyRule]:
        return self.rules.get(rule_id)

    def list_rules(self) -> List[PolicyRule]:
        return list(self.rules.values())
