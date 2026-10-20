"""Viewer session lifecycle — bounded, no page-content retention by default."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ViewerSessionState(str, Enum):
    CREATED = "created"
    NAVIGATING = "navigating"
    CONNECTED = "connected"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CLOSED = "closed"


@dataclass
class ViewerSession:
    session_id: str
    created_at: float
    expires_at: float
    state: ViewerSessionState = ViewerSessionState.CREATED
    target_url: Optional[str] = None
    normalized_url: Optional[Dict[str, Any]] = None
    route_kind: str = "unknown"
    route_id: Optional[str] = None
    gateway_id: Optional[str] = None
    connection_state: str = "idle"
    failure_code: str = ""
    failure_reason: str = ""
    correlation_id: str = ""
    resolved_addresses: List[str] = field(default_factory=list)
    last_activity_at: float = field(default_factory=time.time)
    navigate_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_activity_at = time.time()

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def is_terminal(self) -> bool:
        return self.state in (
            ViewerSessionState.CLOSED,
            ViewerSessionState.CANCELLED,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "target_url": self.target_url,
            "normalized_url": self.normalized_url,
            "route_kind": self.route_kind,
            "route_id": self.route_id,
            "gateway_id": self.gateway_id,
            "connection_state": self.connection_state,
            "failure_code": self.failure_code,
            "failure_reason": self.failure_reason,
            "correlation_id": self.correlation_id,
            "resolved_address_count": len(self.resolved_addresses),
            "navigate_count": self.navigate_count,
            "last_activity_at": self.last_activity_at,
        }


class ViewerSessionStore:
    def __init__(self, *, max_sessions: int = 32, default_ttl: float = 600.0):
        self.max_sessions = max(1, max_sessions)
        self.default_ttl = default_ttl
        self._lock = threading.RLock()
        self._sessions: Dict[str, ViewerSession] = {}

    def create(self, *, ttl: Optional[float] = None) -> ViewerSession:
        with self._lock:
            self._purge_locked()
            if len(self._sessions) >= self.max_sessions:
                self._evict_one_locked()
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError("viewer_session_limit")
            now = time.time()
            sid = secrets.token_hex(16)
            sess = ViewerSession(
                session_id=sid,
                created_at=now,
                expires_at=now + (ttl if ttl is not None else self.default_ttl),
                correlation_id=secrets.token_hex(8),
            )
            self._sessions[sid] = sess
            return sess

    def get(self, session_id: str) -> Optional[ViewerSession]:
        with self._lock:
            self._purge_locked()
            sess = self._sessions.get(session_id)
            if sess is None:
                return None
            if sess.is_expired:
                sess.state = ViewerSessionState.CLOSED
                del self._sessions[session_id]
                return None
            return sess

    def close(self, session_id: str) -> bool:
        with self._lock:
            sess = self._sessions.pop(session_id, None)
            if sess is None:
                return False
            sess.state = ViewerSessionState.CLOSED
            return True

    def list_ids(self) -> List[str]:
        with self._lock:
            self._purge_locked()
            return list(self._sessions.keys())

    def count(self) -> int:
        with self._lock:
            self._purge_locked()
            return len(self._sessions)

    def _purge_locked(self) -> None:
        dead = [
            sid for sid, s in self._sessions.items()
            if s.is_expired or s.state == ViewerSessionState.CLOSED
        ]
        for sid in dead:
            del self._sessions[sid]

    def _evict_one_locked(self) -> None:
        if not self._sessions:
            return
        for sid, s in list(self._sessions.items()):
            if s.is_terminal:
                del self._sessions[sid]
                return
        oldest = min(self._sessions.values(), key=lambda s: s.last_activity_at)
        del self._sessions[oldest.session_id]
