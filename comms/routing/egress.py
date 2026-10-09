"""Controlled egress gateway - disabled by default. Not an open proxy."""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .policy import parse_cidrs, validate_resolved_for_egress

logger = logging.getLogger("aurora.comms.routing.egress")


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
    def __init__(self, config: Optional[EgressConfig] = None):
        self.config = config or EgressConfig()
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._active = 0
        self._lock = threading.Lock()
        self._audit: List[EgressAuditEvent] = []
        self._max_audit = 200
        self._stats = {"accepted": 0, "denied": 0, "connections": 0, "closed": 0}
        self.listen_ok = False
        self.last_error = ""

    def _audit_log(self, action: str, node_id: str, dest: str, outcome: str, reason: str = ""):
        self._audit.append(EgressAuditEvent(ts=time.time(), action=action, node_id=node_id,
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
        if not self.config.enabled or self.config.port <= 0:
            self.listen_ok = False
            self.last_error = "disabled_or_no_port"
            return False
        if self._thread and self._thread.is_alive():
            return True
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.config.bind_host, self.config.port))
            sock.listen(8)
            sock.settimeout(1.0)
            self._sock = sock
            self._stop.clear()
            self._thread = threading.Thread(target=self._accept_loop, name="aurora-egress", daemon=True)
            self._thread.start()
            self.listen_ok = True
            self.last_error = ""
            logger.info("egress gateway listening on %s:%s (not an open proxy)",
                        self.config.bind_host, self.config.port)
            return True
        except Exception as e:
            self.listen_ok = False
            self.last_error = str(e)
            logger.error("egress bind failed: %s", e)
            return False

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                assert self._sock is not None
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            try:
                conn.settimeout(2.0)
                _ = conn.recv(256)
                conn.sendall(b"AURORA_EGRESS_V0.1 policy-controlled; not an open proxy\n")
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
                self._stats["closed"] += 1

    def stop(self):
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self.listen_ok = False

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.config.enabled, "listen_ok": self.listen_ok,
            "bind": f"{self.config.bind_host}:{self.config.port}" if self.config.port else None,
            "active_connections": self._active, "max_connections": self.config.max_connections,
            "last_error": self.last_error, "stats": dict(self._stats),
            "audit_tail": [e.to_dict() for e in self._audit[-20:]],
        }

    def stats(self) -> Dict[str, int]:
        return dict(self._stats)
