"""Controlled egress boundary — disabled by default.

v0.1 status:
  - Policy authorization (open_outbound) is implemented and testable.
  - TCP relay / proxy listener is NOT implemented.
  - start_listener() refuses to bind; documented as future work.
  - No open proxy, no firewall mutation, no implicit host-routing changes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .policy import parse_cidrs, validate_resolved_for_egress

logger = logging.getLogger("aurora.comms.routing.egress")

RELAY_IMPLEMENTED = False


@dataclass
class EgressConfig:
    enabled: bool = False
    bind_host: str = "127.0.0.1"
    port: int = 0
    allowed_cidrs: List[str] = field(default_factory=list)
    allowed_ports: Set[int] = field(default_factory=set)
    max_connections: int = 32
    connect_timeout: float = 5.0
    deny_private: bool = True
    authorized_node_ids: Set[str] = field(default_factory=set)


@dataclass
class EgressAuditEvent:
    ts: float
    action: str
    node_id: str
    destination: str
    outcome: str
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"ts": self.ts, "action": self.action, "node_id": self.node_id,
                "destination": self.destination, "outcome": self.outcome, "reason": self.reason}


class EgressGateway:
    """Policy gate for outbound connections. Relay listener is not implemented."""

    def __init__(self, config: Optional[EgressConfig] = None):
        self.config = config or EgressConfig()
        self._active = 0
        self._lock = __import__("threading").Lock()
        self._audit: List[EgressAuditEvent] = []
        self._max_audit = 200
        self._stats = {"accepted": 0, "denied": 0, "connections": 0, "closed": 0}
        self.listen_ok = False
        self.last_error = ""
        self.relay_implemented = RELAY_IMPLEMENTED

    def _audit_log(self, action: str, node_id: str, dest: str, outcome: str, reason: str = ""):
        self._audit.append(EgressAuditEvent(
            ts=time.time(), action=action, node_id=node_id,
            destination=dest[:128], outcome=outcome, reason=reason))
        if len(self._audit) > self._max_audit:
            self._audit = self._audit[-self._max_audit:]

    def authorize_request(self, node_id: str, addresses: List[str], port: int) -> Tuple[bool, str]:
        if not self.config.enabled:
            return False, "egress_disabled"
        if self.config.authorized_node_ids and node_id not in self.config.authorized_node_ids:
            return False, "node_not_authorized"
        cidrs = parse_cidrs(self.config.allowed_cidrs)
        return validate_resolved_for_egress(
            addresses, port, allowed_cidrs=cidrs or None,
            allowed_ports=self.config.allowed_ports or None,
            deny_private=self.config.deny_private)

    def open_outbound(self, node_id: str, address: str, port: int) -> Tuple[bool, str, Optional[float]]:
        ok, reason = self.authorize_request(node_id, [address], port)
        if not ok:
            self._stats["denied"] += 1
            self._audit_log("open", node_id, f"{address}:{port}", "denied", reason)
            return False, reason, None
        with self._lock:
            if self._active >= self.config.max_connections:
                self._stats["denied"] += 1
                self._audit_log("open", node_id, f"{address}:{port}", "denied", "max_connections")
                return False, "max_connections", None
            self._active += 1
        import socket
        t0 = time.time()
        try:
            sock = socket.create_connection((address, port), timeout=self.config.connect_timeout)
            latency = (time.time() - t0) * 1000
            sock.close()
            self._stats["accepted"] += 1
            self._stats["connections"] += 1
            self._stats["closed"] += 1
            self._audit_log("open", node_id, f"{address}:{port}", "ok")
            return True, "ok", latency
        except socket.timeout:
            self._stats["denied"] += 1
            self._audit_log("open", node_id, f"{address}:{port}", "timeout")
            return False, "timeout", None
        except OSError as e:
            self._stats["denied"] += 1
            self._audit_log("open", node_id, f"{address}:{port}", "error", str(e))
            return False, str(e), None
        finally:
            with self._lock:
                self._active = max(0, self._active - 1)

    def start_listener(self) -> bool:
        """v0.1: relay is not implemented. Never binds a proxy socket."""
        self.listen_ok = False
        if not self.config.enabled:
            self.last_error = "egress_disabled"
            logger.info("egress gateway disabled (AURORA_EGRESS_GATEWAY_ENABLED)")
            return False
        self.last_error = "relay_not_implemented"
        logger.warning(
            "egress relay/proxy listener is NOT implemented in v0.1; "
            "refusing to bind. Policy authorization (open_outbound) remains available.")
        return False

    def stop(self):
        self.listen_ok = False
        self.last_error = ""

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "listen_ok": self.listen_ok,
            "relay_implemented": self.relay_implemented,
            "bind": (f"{self.config.bind_host}:{self.config.port}" if self.config.port else None),
            "active_connections": self._active,
            "max_connections": self.config.max_connections,
            "last_error": self.last_error,
            "stats": dict(self._stats),
            "audit_tail": [e.to_dict() for e in self._audit[-20:]],
            "note": "policy authorization only; TCP relay/proxy not implemented in v0.1",
        }

    def stats(self) -> Dict[str, int]:
        return dict(self._stats)
