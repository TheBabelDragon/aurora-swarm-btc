"""Health, detection, false-positive, enforcement, and subsystem failure metrics."""

from __future__ import annotations

import time
from typing import Any, Dict

from pydantic import BaseModel, Field


class AegisDiagnostics(BaseModel):
    started_at: float = Field(default_factory=time.time)
    events_received: int = 0
    events_dropped: int = 0  # queue saturation / back-pressure
    decisions_allow: int = 0
    decisions_deny: int = 0
    decisions_quarantine: int = 0
    decisions_rate_limit: int = 0
    containment_success: int = 0
    containment_failure: int = 0
    integrity_checks: int = 0
    integrity_failures: int = 0
    watchdog_healthy: bool = True
    model_adapters_enabled: bool = False
    last_event_ts: float = 0.0
    last_error: str = ""

    def record_decision(self, outcome: str) -> None:
        if outcome == "allow":
            self.decisions_allow += 1
        elif outcome == "deny":
            self.decisions_deny += 1
        elif outcome == "quarantine":
            self.decisions_quarantine += 1
        elif outcome == "rate_limit":
            self.decisions_rate_limit += 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "uptime_s": round(time.time() - self.started_at, 1),
            "events_received": self.events_received,
            "events_dropped": self.events_dropped,
            "decisions": {
                "allow": self.decisions_allow,
                "deny": self.decisions_deny,
                "quarantine": self.decisions_quarantine,
                "rate_limit": self.decisions_rate_limit,
            },
            "containment": {
                "success": self.containment_success,
                "failure": self.containment_failure,
            },
            "integrity_checks": self.integrity_checks,
            "integrity_failures": self.integrity_failures,
            "watchdog_healthy": self.watchdog_healthy,
            "model_adapters_enabled": self.model_adapters_enabled,
            "last_event_ts": self.last_event_ts,
            "last_error": self.last_error or None,
        }
