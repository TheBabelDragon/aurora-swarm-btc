"""Narrowly scoped, authorized enforcement actions against registered Aurora resources.

No arbitrary remote shell, unrestricted host control, or network-wide shutdown.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field


class ContainmentKind(str, Enum):
    REVOKE_CAPABILITY = "revoke_capability"
    REVOKE_IDENTITY = "revoke_identity"
    PAUSE_WORKER = "pause_worker"  # soft: mark unauthorized, stop accepting jobs
    QUARANTINE_WORKER = "quarantine_worker"
    RATE_LIMIT_ACTOR = "rate_limit_actor"
    REJECT_ROUTE = "reject_route"
    LOG_ONLY = "log_only"


class ContainmentAction(BaseModel):
    action_id: str = Field(default_factory=lambda: f"ca-{time.time_ns()}")
    kind: ContainmentKind
    target_id: str
    reason: str = ""
    authorized_by: str = "policy"  # policy | operator | quarantine_role
    decision_id: Optional[str] = None
    event_id: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=time.time)


class ContainmentResult(BaseModel):
    action_id: str
    success: bool
    message: str = ""
    ts: float = Field(default_factory=time.time)


class ContainmentExecutor:
    """Executes only explicitly authorized, scoped actions."""

    ALLOWED_KINDS = set(ContainmentKind)

    def __init__(
        self,
        *,
        revoke_capability_fn: Optional[Callable[[str, str], bool]] = None,
        revoke_identity_fn: Optional[Callable[[str, str], bool]] = None,
        pause_worker_fn: Optional[Callable[[str], bool]] = None,
    ):
        self._revoke_cap = revoke_capability_fn
        self._revoke_id = revoke_identity_fn
        self._pause = pause_worker_fn
        self._history: List[ContainmentResult] = []
        self._rate_limits: Dict[str, float] = {}  # actor -> until

    def execute(self, action: ContainmentAction) -> ContainmentResult:
        if action.kind not in self.ALLOWED_KINDS:
            result = ContainmentResult(
                action_id=action.action_id,
                success=False,
                message=f"Unsupported containment kind: {action.kind}",
            )
            self._history.append(result)
            return result

        # Only policy / operator / quarantine_role may authorize
        if action.authorized_by not in ("policy", "operator", "quarantine_role", "aegis"):
            result = ContainmentResult(
                action_id=action.action_id,
                success=False,
                message=f"Unauthorized containment issuer: {action.authorized_by}",
            )
            self._history.append(result)
            return result

        ok = False
        msg = ""
        try:
            if action.kind == ContainmentKind.LOG_ONLY:
                ok = True
                msg = "logged only"
            elif action.kind == ContainmentKind.REVOKE_CAPABILITY:
                cap = action.params.get("capability") or ""
                if self._revoke_cap and cap:
                    ok = bool(self._revoke_cap(action.target_id, cap))
                    msg = f"revoke {cap}: {ok}"
                else:
                    msg = "revoke_capability unavailable or missing capability name"
            elif action.kind == ContainmentKind.REVOKE_IDENTITY:
                if self._revoke_id:
                    ok = bool(self._revoke_id(action.target_id, action.reason))
                    msg = f"revoke identity: {ok}"
                else:
                    msg = "revoke_identity unavailable"
            elif action.kind in (ContainmentKind.PAUSE_WORKER, ContainmentKind.QUARANTINE_WORKER):
                if self._pause:
                    ok = bool(self._pause(action.target_id))
                    msg = f"{action.kind.value}: {ok}"
                else:
                    # Soft local mark even without external pause hook
                    self._rate_limits[action.target_id] = time.time() + 3600
                    ok = True
                    msg = f"{action.kind.value}: local rate-limit applied"
            elif action.kind == ContainmentKind.RATE_LIMIT_ACTOR:
                until = time.time() + float(action.params.get("seconds", 300))
                self._rate_limits[action.target_id] = until
                ok = True
                msg = f"rate-limited until {until}"
            elif action.kind == ContainmentKind.REJECT_ROUTE:
                ok = True
                msg = "route rejection recorded (caller must honor decision)"
            else:
                msg = "no handler"
        except Exception as e:
            ok = False
            msg = f"containment error: {e}"

        result = ContainmentResult(action_id=action.action_id, success=ok, message=msg)
        self._history.append(result)
        return result

    def is_rate_limited(self, actor_id: str) -> bool:
        until = self._rate_limits.get(actor_id)
        if until is None:
            return False
        if time.time() > until:
            del self._rate_limits[actor_id]
            return False
        return True

    def recent(self, limit: int = 50) -> List[ContainmentResult]:
        return list(reversed(self._history[-limit:]))
