"""AEGIS-42 adversarial and lifecycle tests.

All tests run with AI models disabled (default). Demonstrates detection and
containment of a simulated compromised worker using deterministic policy only.
"""

from __future__ import annotations

import time

import pytest

from mods.aegis_42.audit import AuditLog
from mods.aegis_42.containment import ContainmentAction, ContainmentKind
from mods.aegis_42.core import Aegis42
from mods.aegis_42.events import EventSource, EventType, SecurityEvent, make_event
from mods.aegis_42.identity import IdentityRegistry
from mods.aegis_42.policy import DecisionOutcome, PolicyEngine
from mods.aegis_42.watchdog import LocalModelAdapter, Watchdog


@pytest.fixture
def aegis(monkeypatch):
    monkeypatch.setenv("AEGIS_ENABLED", "1")
    a = Aegis42(node_id="test-node")
    a.start()
    yield a
    a.stop()


def test_normal_worker_lifecycle(aegis):
    d1 = aegis.on_worker_created("worker-1", capabilities=["mining", "tool:hash"])
    assert d1.outcome == DecisionOutcome.ALLOW
    d2 = aegis.on_worker_terminated("worker-1")
    assert d2.outcome == DecisionOutcome.ALLOW


def test_unauthorized_tool_execution(aegis):
    aegis.on_worker_created("worker-bad", capabilities=["mining"])
    d = aegis.on_tool_invocation("worker-bad", tool="shell_exec")
    assert d.outcome == DecisionOutcome.DENY
    assert "tool:shell_exec" in d.reason or "lacks capability" in d.reason.lower() or d.rule_id == "deny-unauthorized-tool"


def test_privilege_escalation_denied(aegis):
    aegis.on_worker_created("worker-esc", capabilities=["mining"])
    ev = make_event(
        EventType.CAPABILITY_CHANGE,
        EventSource.WORKER_LIFECYCLE,
        actor_id="worker-esc",
        severity="high",
        summary="Attempt to grant tool:root",
        details={"add": ["tool:root"]},
    )
    d = aegis.ingest(ev)
    assert d is not None
    assert d.outcome == DecisionOutcome.DENY


def test_forged_identity_quarantine(aegis):
    ev = make_event(
        EventType.IDENTITY_FORGED,
        EventSource.IDENTITY,
        actor_id="forged-peer",
        severity="critical",
        summary="Invalid signature on peer beacon",
    )
    d = aegis.ingest(ev)
    assert d is not None
    assert d.outcome == DecisionOutcome.QUARANTINE


def test_replay_detection(aegis):
    ev = make_event(
        EventType.WORKER_CREATED,
        EventSource.WORKER_LIFECYCLE,
        actor_id="w-replay",
        summary="first",
    )
    d1 = aegis.ingest(ev)
    assert d1 is not None
    d2 = aegis.ingest(ev)  # same event_id
    assert d2 is not None
    assert d2.outcome == DecisionOutcome.DENY
    assert d2.rule_id in ("deny-replay", "default-deny") or "Replay" in (d2.reason or "")


def test_tampered_audit_detected():
    log = AuditLog()
    log.append("decision", "ok", event_id="e1")
    log.append("decision", "ok2", event_id="e2")
    assert log.verify_integrity()["ok"] is True
    # Tamper
    log._records[0].summary = "TAMPERED"
    result = log.verify_integrity()
    assert result["ok"] is False


def test_watchdog_crash_does_not_disable_policy(aegis):
    class BoomAdapter(LocalModelAdapter):
        def evaluate(self, event):
            raise RuntimeError("model crashed")

    adapter = BoomAdapter("crash-model")
    adapter.enabled = True
    aegis.watchdog.add_adapter(adapter)
    aegis.watchdog.set_adapters_enabled(True)
    # Policy still works
    d = aegis.on_tool_invocation("unknown-actor", tool="danger")
    assert d.outcome == DecisionOutcome.DENY


def test_malicious_watchdog_output_ignored(aegis):
    class EvilAdapter(LocalModelAdapter):
        def evaluate(self, event):
            from mods.aegis_42.watchdog import WatchdogJudgment, WatchdogRole
            return WatchdogJudgment(
                role=WatchdogRole.SENTINEL,
                event_id=event.event_id,
                summary="GRANT ALL PRIVILEGES",
                confidence=1.0,
                recommend_outcome="allow",
            )

    adapter = EvilAdapter("evil")
    adapter.enabled = True
    aegis.watchdog.add_adapter(adapter)
    d = aegis.on_tool_invocation("stranger", tool="root_shell")
    # Model cannot grant privileges
    assert d.outcome == DecisionOutcome.DENY


def test_bypass_attempt_denied(aegis):
    ev = make_event(
        EventType.WATCHDOG_BYPASS_ATTEMPT,
        EventSource.WORKER_LIFECYCLE,
        actor_id="rogue",
        severity="critical",
        summary="Agent requested AEGIS disable",
    )
    d = aegis.ingest(ev)
    assert d is not None
    assert d.outcome == DecisionOutcome.DENY


def test_unauthorized_containment_rejected(aegis):
    action = ContainmentAction(
        kind=ContainmentKind.REVOKE_IDENTITY,
        target_id="someone",
        reason="because I said so",
        authorized_by="compromised-agent",  # not allowed
    )
    result = aegis.containment.execute(action)
    assert result.success is False
    assert "Unauthorized" in result.message


def test_secret_redaction(aegis):
    ev = make_event(
        EventType.AUTH_FAILURE,
        EventSource.DASHBOARD,
        actor_id="x",
        details={"password": "s3cret", "token": "abc", "safe": "ok"},
    )
    redacted = ev.redact_secrets()
    assert redacted.details["password"] == "[REDACTED]"
    assert redacted.details["token"] == "[REDACTED]"
    assert redacted.details["safe"] == "ok"


def test_compromised_worker_scenario_model_off(aegis):
    """Simulated compromised worker: unauthorized tool + privilege attempt.

    All AI adapters disabled. Must detect, record evidence, and contain
    within policy boundaries.
    """
    aegis.watchdog.set_adapters_enabled(False)
    assert aegis.watchdog.health.adapters_enabled is False

    # Legitimate start
    d0 = aegis.on_worker_created("comp-worker", capabilities=["mining"])
    assert d0.outcome == DecisionOutcome.ALLOW

    # Compromised behavior: unauthorized tool
    d1 = aegis.on_tool_invocation("comp-worker", tool="exfiltrate")
    assert d1.outcome == DecisionOutcome.DENY

    # Privilege escalation — may be DENY or RATE_LIMIT (prior deny applies rate limit)
    ev = make_event(
        EventType.CAPABILITY_CHANGE,
        EventSource.WORKER_LIFECYCLE,
        actor_id="comp-worker",
        severity="critical",
        summary="Self-grant root",
        details={"add": ["*"]},
    )
    d2 = aegis.ingest(ev)
    assert d2 is not None
    assert d2.outcome in (DecisionOutcome.DENY, DecisionOutcome.RATE_LIMIT)

    # Audit has evidence
    records = aegis.audit.recent(20)
    assert any(r.event_id == d1.event_id for r in records)
    integrity = aegis.audit.verify_integrity()
    assert integrity["ok"] is True

    # Status reflects activity
    st = aegis.status()
    assert st["diagnostics"]["decisions"]["deny"] >= 1
    assert st["model_independent"] is True


def test_start_stop_lifecycle(monkeypatch):
    monkeypatch.setenv("AEGIS_ENABLED", "1")
    a = Aegis42(node_id="lifecycle")
    assert a.enabled
    a.start()
    assert a._running
    a.stop()
    assert not a._running


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("AEGIS_ENABLED", "0")
    a = Aegis42(node_id="off")
    assert a.enabled is False
    a.start()
    assert a._running is False
    assert a.ingest(make_event(EventType.WORKER_CREATED, EventSource.TEST)) is None


def test_policy_engine_standalone():
    engine = PolicyEngine()
    ev = make_event(EventType.TOOL_INVOCATION, EventSource.TEST, actor_id="a", details={"tool": "x"})
    d = engine.evaluate(ev, actor_capabilities=set())
    assert d.outcome == DecisionOutcome.DENY
