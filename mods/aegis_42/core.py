"""AEGIS-42 core — integrates into Aurora node lifecycle.

Starts with the node, evaluates events through deterministic policy,
records audit evidence, and executes only authorized containment.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Set

from .audit import AuditLog
from .containment import (
    ContainmentAction,
    ContainmentExecutor,
    ContainmentKind,
    ContainmentResult,
)
from .diagnostics import AegisDiagnostics
from .events import EventSource, EventType, SecurityEvent, make_event
from .identity import IdentityRegistry
from .policy import DecisionOutcome, PolicyDecision, PolicyEngine
from .watchdog import Watchdog

logger = logging.getLogger("aurora.aegis42")

_INSTANCE: Optional["Aegis42"] = None
_LOCK = threading.Lock()


class Aegis42:
    """First-class security oversight for an Aurora node."""

    QUEUE_MAX = 1000

    def __init__(self, node_id: Optional[str] = None):
        self.node_id = node_id or os.getenv("AURORA_NODE_ID") or "node"
        self.enabled = os.getenv("AEGIS_ENABLED", "1").strip().lower() not in ("0", "false", "off")
        self.policy = PolicyEngine()
        self.identity = IdentityRegistry()
        self.audit = AuditLog()
        self.watchdog = Watchdog()
        self.diagnostics = AegisDiagnostics()
        self.containment = ContainmentExecutor(
            revoke_capability_fn=self.identity.revoke_capability,
            revoke_identity_fn=lambda iid, reason: self.identity.revoke_identity(iid, reason),
        )
        self._queue: Deque[SecurityEvent] = deque(maxlen=self.QUEUE_MAX)
        self._seen_event_ids: Set[str] = set()
        self._max_seen = 5000
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._comms = None  # optional CommsLayer reference

        # Bootstrap system identity
        self.identity.register(
            "aegis",
            node_id=self.node_id,
            kind="system",
            capabilities=["oversight", "policy", "audit", "containment"],
            trust_level="operator",
        )

    def attach_comms(self, comms: Any) -> None:
        self._comms = comms
        if hasattr(comms, "node_id"):
            self.node_id = comms.node_id

    def start(self) -> None:
        if not self.enabled:
            logger.info("AEGIS-42 disabled via AEGIS_ENABLED")
            return
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._process_loop, name="aegis42", daemon=True)
        self._thread.start()
        self.audit.append("system", "AEGIS-42 started", payload={"node_id": self.node_id})
        logger.info("AEGIS-42 started on node=%s", self.node_id)

    def stop(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.audit.append("system", "AEGIS-42 stopped", payload={"node_id": self.node_id})
        logger.info("AEGIS-42 stopped")

    def ingest(self, event: SecurityEvent) -> Optional[PolicyDecision]:
        """Accept a security event. Applies redaction, replay detection, policy."""
        if not self.enabled:
            return None

        # Replay detection
        if event.event_id in self._seen_event_ids:
            replay = make_event(
                EventType.REPLAY_DETECTED,
                EventSource.POLICY_ENGINE,
                node_id=self.node_id,
                actor_id=event.actor_id,
                severity="high",
                summary=f"Replay of event {event.event_id}",
                details={"original_event_id": event.event_id},
            )
            return self._handle(replay)

        self._seen_event_ids.add(event.event_id)
        if len(self._seen_event_ids) > self._max_seen:
            # drop oldest roughly
            self._seen_event_ids = set(list(self._seen_event_ids)[-self._max_seen // 2:])

        event = event.redact_secrets()
        if len(self._queue) >= self.QUEUE_MAX:
            self.diagnostics.events_dropped += 1
            self.audit.append(
                "system",
                "Event queue saturation; dropping",
                payload={"event_type": event.event_type.value},
            )
            return None

        self._queue.append(event)
        self.diagnostics.events_received += 1
        self.diagnostics.last_event_ts = event.ts
        return self._handle(event)

    def _handle(self, event: SecurityEvent) -> PolicyDecision:
        caps = self.identity.capabilities_of(event.actor_id or "")
        trusted = self.identity.is_trusted(event.actor_id or "")

        # Rate-limit check
        if event.actor_id and self.containment.is_rate_limited(event.actor_id):
            decision = PolicyDecision(
                outcome=DecisionOutcome.RATE_LIMIT,
                rule_id="active-rate-limit",
                event_id=event.event_id,
                actor_id=event.actor_id,
                reason="Actor is currently rate-limited",
            )
            self.diagnostics.record_decision(decision.outcome.value)
            self.audit.append(
                "decision",
                decision.reason,
                event_id=event.event_id,
                decision_id=decision.decision_id,
                actor_id=event.actor_id,
                payload=decision.model_dump(),
            )
            return decision

        decision = self.policy.evaluate(
            event,
            actor_capabilities=caps,
            actor_trusted=trusted,
        )
        self.diagnostics.record_decision(decision.outcome.value)

        # Advisory watchdog (never authoritative)
        judgments = self.watchdog.evaluate(event)
        if judgments:
            decision.model_advisory = "; ".join(j.summary for j in judgments[:3])

        self.audit.append(
            "decision",
            f"{decision.outcome.value}: {decision.reason}",
            event_id=event.event_id,
            decision_id=decision.decision_id,
            actor_id=event.actor_id,
            payload={
                "outcome": decision.outcome.value,
                "rule_id": decision.rule_id,
                "event_type": event.event_type.value,
            },
        )

        # Authorized containment only
        if decision.outcome == DecisionOutcome.QUARANTINE and event.actor_id:
            action = ContainmentAction(
                kind=ContainmentKind.QUARANTINE_WORKER,
                target_id=event.actor_id,
                reason=decision.reason,
                authorized_by="policy",
                decision_id=decision.decision_id,
                event_id=event.event_id,
            )
            result = self.containment.execute(action)
            if result.success:
                self.diagnostics.containment_success += 1
            else:
                self.diagnostics.containment_failure += 1
            self.audit.append(
                "containment",
                result.message,
                event_id=event.event_id,
                decision_id=decision.decision_id,
                actor_id=event.actor_id,
                payload=result.model_dump(),
            )
        elif decision.outcome == DecisionOutcome.DENY and event.event_type == EventType.TOOL_INVOCATION:
            # Soft: rate-limit repeated unauthorized tool use
            if event.actor_id:
                action = ContainmentAction(
                    kind=ContainmentKind.RATE_LIMIT_ACTOR,
                    target_id=event.actor_id,
                    reason=decision.reason,
                    authorized_by="policy",
                    decision_id=decision.decision_id,
                    event_id=event.event_id,
                    params={"seconds": 60},
                )
                self.containment.execute(action)

        return decision

    def _process_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                # Periodic integrity check
                check = self.audit.verify_integrity()
                self.diagnostics.integrity_checks += 1
                if not check.get("ok"):
                    self.diagnostics.integrity_failures += 1
                    self.diagnostics.last_error = str(check)
                    logger.warning("AEGIS audit integrity failure: %s", check)
            except Exception as e:
                self.diagnostics.last_error = str(e)
            self._stop_event.wait(5.0)

    # --- Convenience producers for Aurora integration ---

    def on_worker_created(self, worker_id: str, capabilities: Optional[List[str]] = None) -> PolicyDecision:
        try:
            self.identity.register(
                worker_id,
                node_id=self.node_id,
                kind="worker",
                capabilities=capabilities or ["mining"],
                trust_level="provisional",
            )
        except ValueError:
            pass  # already revoked
        ev = make_event(
            EventType.WORKER_CREATED,
            EventSource.WORKER_LIFECYCLE,
            node_id=self.node_id,
            actor_id=worker_id,
            summary=f"Worker {worker_id} created",
            details={"capabilities": capabilities or []},
        )
        return self.ingest(ev)  # type: ignore

    def on_worker_terminated(self, worker_id: str) -> PolicyDecision:
        ev = make_event(
            EventType.WORKER_TERMINATED,
            EventSource.WORKER_LIFECYCLE,
            node_id=self.node_id,
            actor_id=worker_id,
            summary=f"Worker {worker_id} terminated",
        )
        return self.ingest(ev)  # type: ignore

    def on_tool_invocation(self, actor_id: str, tool: str, **details: Any) -> PolicyDecision:
        ev = make_event(
            EventType.TOOL_INVOCATION,
            EventSource.WORKER_LIFECYCLE,
            node_id=self.node_id,
            actor_id=actor_id,
            severity="medium",
            summary=f"Tool {tool} by {actor_id}",
            details={"tool": tool, **details},
        )
        return self.ingest(ev)  # type: ignore

    def on_auth_failure(self, actor_id: Optional[str], reason: str) -> PolicyDecision:
        ev = make_event(
            EventType.AUTH_FAILURE,
            EventSource.DASHBOARD,
            node_id=self.node_id,
            actor_id=actor_id,
            severity="high",
            summary=reason,
            details={"reason": reason},
        )
        return self.ingest(ev)  # type: ignore

    def on_route_decision(self, target: str, allowed: bool, **details: Any) -> PolicyDecision:
        et = EventType.EGRESS_DECISION if "egress" in details else EventType.ROUTE_SELECTED
        ev = make_event(
            et,
            EventSource.ROUTING,
            node_id=self.node_id,
            target_id=target,
            severity="info" if allowed else "medium",
            summary=f"Route to {target}: {'allow' if allowed else 'deny'}",
            details={"allowed": allowed, **details},
        )
        return self.ingest(ev)  # type: ignore

    def status(self) -> Dict[str, Any]:
        integ = self.audit.verify_integrity()
        return {
            "enabled": self.enabled,
            "running": self._running,
            "node_id": self.node_id,
            "queue_depth": len(self._queue),
            "identities": len(self.identity.list_identities()),
            "diagnostics": self.diagnostics.snapshot(),
            "audit_integrity": integ,
            "watchdog": self.watchdog.health.model_dump(),
            "model_independent": True,
        }


def get_aegis() -> Optional[Aegis42]:
    return _INSTANCE


def start_aegis(node_id: Optional[str] = None, comms: Any = None) -> Aegis42:
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = Aegis42(node_id=node_id)
        if comms is not None:
            _INSTANCE.attach_comms(comms)
        _INSTANCE.start()
        return _INSTANCE


def stop_aegis() -> None:
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is not None:
            _INSTANCE.stop()
