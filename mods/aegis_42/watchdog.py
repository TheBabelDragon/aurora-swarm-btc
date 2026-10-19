"""Supervised watchdog interface, health state, optional local-model adapters.

Local models are advisory only. Disabling them does not disable baseline security.
No automatic upload of prompts or private data.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from .events import SecurityEvent


class WatchdogRole(str, Enum):
    SENTINEL = "sentinel"      # behavioral anomaly detection
    INQUEST = "inquest"        # evidence correlation
    QUARANTINE = "quarantine"  # policy-authorized containment suggestions
    CONCLAVE = "conclave"      # independent review / trust evaluation


class WatchdogJudgment(BaseModel):
    role: WatchdogRole
    event_id: str
    severity: str = "info"
    summary: str = ""
    confidence: float = 0.0  # 0..1 advisory
    recommend_outcome: Optional[str] = None  # never authoritative
    ts: float = Field(default_factory=time.time)
    model_id: Optional[str] = None


class WatchdogHealth(BaseModel):
    healthy: bool = True
    last_check: float = Field(default_factory=time.time)
    consecutive_failures: int = 0
    last_error: str = ""
    adapters_enabled: bool = False


class LocalModelAdapter:
    """Optional local inference adapter. Disabled by default.

    Implementations must not upload data. Output is advisory only.
    """

    def __init__(self, model_id: str = "local-stub"):
        self.model_id = model_id
        self.enabled = False

    def evaluate(self, event: SecurityEvent) -> Optional[WatchdogJudgment]:
        if not self.enabled:
            return None
        # Stub: no real model. Real adapters plug in here without changing policy authority.
        return WatchdogJudgment(
            role=WatchdogRole.SENTINEL,
            event_id=event.event_id,
            severity=event.severity,
            summary=f"advisory note from {self.model_id}",
            confidence=0.0,
            model_id=self.model_id,
        )


class Watchdog:
    """Supervised watchdog. Baseline security works with all adapters disabled."""

    def __init__(self):
        self.health = WatchdogHealth()
        self.adapters: List[LocalModelAdapter] = []
        self._judgments: List[WatchdogJudgment] = []
        self._max_judgments = 200

    def add_adapter(self, adapter: LocalModelAdapter) -> None:
        self.adapters.append(adapter)
        self.health.adapters_enabled = any(a.enabled for a in self.adapters)

    def set_adapters_enabled(self, enabled: bool) -> None:
        for a in self.adapters:
            a.enabled = enabled
        self.health.adapters_enabled = enabled and bool(self.adapters)

    def evaluate(self, event: SecurityEvent) -> List[WatchdogJudgment]:
        judgments: List[WatchdogJudgment] = []
        try:
            for adapter in self.adapters:
                j = adapter.evaluate(event)
                if j:
                    judgments.append(j)
            self.health.healthy = True
            self.health.consecutive_failures = 0
            self.health.last_error = ""
        except Exception as e:
            self.health.consecutive_failures += 1
            self.health.last_error = str(e)
            if self.health.consecutive_failures >= 3:
                self.health.healthy = False
        self.health.last_check = time.time()
        for j in judgments:
            self._judgments.append(j)
        if len(self._judgments) > self._max_judgments:
            self._judgments = self._judgments[-self._max_judgments:]
        return judgments

    def recent_judgments(self, limit: int = 20) -> List[WatchdogJudgment]:
        return list(reversed(self._judgments[-limit:]))
