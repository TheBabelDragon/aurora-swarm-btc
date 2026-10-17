"""Delivery states, message envelopes, acknowledgments, and bounded deduplication.

Phase 1 of Aurora Autonomic Fabric. Delivery semantics are explicit:

  ACCEPTED   — local queue / transport accepted the message (not end-to-end)
  FORWARDED  — a relay or intermediate hop accepted the message
  DELIVERED  — destination-level authenticated acknowledgment received
  FAILED     — exhausted retries, hop limit, expiry, or permanent error
  UNKNOWN    — no conclusive outcome yet (in-flight / missing ACK)

Never report DELIVERED solely because a local queue accepted or a relay
forwarded. Hop-level ACKs are distinct from destination-level ACKs.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Set, Tuple

logger = logging.getLogger("aurora.comms.routing.delivery")


class DeliveryState(str, Enum):
    ACCEPTED = "ACCEPTED"
    FORWARDED = "FORWARDED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class AckKind(str, Enum):
    """Hop-level vs destination-level acknowledgment."""
    HOP = "hop"
    DESTINATION = "destination"


@dataclass
class MessageEnvelope:
    """Wire-oriented envelope with identity, expiry, hop limit, and anti-replay."""

    message_id: str
    destination_id: str
    source_id: str
    payload: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    hop_limit: int = 8
    hop_count: int = 0
    sequence: int = 0
    nonce: str = ""
    signature: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.message_id:
            self.message_id = secrets.token_hex(16)
        if not self.nonce:
            self.nonce = secrets.token_hex(8)
        if self.expires_at <= 0:
            self.expires_at = self.created_at + 120.0

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def hops_remaining(self) -> int:
        return max(0, self.hop_limit - self.hop_count)

    def can_forward(self) -> bool:
        return not self.is_expired and self.hops_remaining > 0

    def increment_hop(self) -> None:
        self.hop_count += 1

    def signing_payload(self) -> bytes:
        parts = [
            self.message_id,
            self.destination_id,
            self.source_id,
            str(self.created_at),
            str(self.expires_at),
            str(self.hop_limit),
            str(self.hop_count),
            str(self.sequence),
            self.nonce,
        ]
        return "|".join(parts).encode("utf-8")

    def sign(self, secret: bytes) -> None:
        self.signature = hmac.new(secret, self.signing_payload(), hashlib.sha256).hexdigest()

    def verify(self, secret: bytes) -> bool:
        if not self.signature:
            return False
        expected = hmac.new(secret, self.signing_payload(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(self.signature, expected)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "destination_id": self.destination_id,
            "source_id": self.source_id,
            "payload": dict(self.payload),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "hop_limit": self.hop_limit,
            "hop_count": self.hop_count,
            "sequence": self.sequence,
            "nonce": self.nonce,
            "signature": self.signature,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageEnvelope":
        return cls(
            message_id=str(data.get("message_id") or ""),
            destination_id=str(data.get("destination_id") or ""),
            source_id=str(data.get("source_id") or ""),
            payload=dict(data.get("payload") or {}),
            created_at=float(data.get("created_at") or time.time()),
            expires_at=float(data.get("expires_at") or 0),
            hop_limit=int(data.get("hop_limit") or 8),
            hop_count=int(data.get("hop_count") or 0),
            sequence=int(data.get("sequence") or 0),
            nonce=str(data.get("nonce") or ""),
            signature=str(data.get("signature") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class Acknowledgment:
    """Authenticated acknowledgment tied to message_id and destination identity."""

    message_id: str
    ack_kind: AckKind
    from_id: str
    destination_id: str
    state: DeliveryState
    created_at: float = field(default_factory=time.time)
    nonce: str = ""
    signature: str = ""
    reason: str = ""
    latency_ms: Optional[float] = None

    def __post_init__(self):
        if not self.nonce:
            self.nonce = secrets.token_hex(8)

    def signing_payload(self) -> bytes:
        parts = [
            self.message_id,
            self.ack_kind.value,
            self.from_id,
            self.destination_id,
            self.state.value,
            str(self.created_at),
            self.nonce,
            self.reason or "",
        ]
        return "|".join(parts).encode("utf-8")

    def sign(self, secret: bytes) -> None:
        self.signature = hmac.new(secret, self.signing_payload(), hashlib.sha256).hexdigest()

    def verify(self, secret: bytes) -> bool:
        if not self.signature:
            return False
        expected = hmac.new(secret, self.signing_payload(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(self.signature, expected)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "ack_kind": self.ack_kind.value,
            "from_id": self.from_id,
            "destination_id": self.destination_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "nonce": self.nonce,
            "signature": self.signature,
            "reason": self.reason,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Acknowledgment":
        kind = data.get("ack_kind") or "hop"
        state = data.get("state") or "UNKNOWN"
        return cls(
            message_id=str(data.get("message_id") or ""),
            ack_kind=AckKind(kind) if kind in AckKind._value2member_map_ else AckKind.HOP,
            from_id=str(data.get("from_id") or ""),
            destination_id=str(data.get("destination_id") or ""),
            state=DeliveryState(state) if state in DeliveryState._value2member_map_ else DeliveryState.UNKNOWN,
            created_at=float(data.get("created_at") or time.time()),
            nonce=str(data.get("nonce") or ""),
            signature=str(data.get("signature") or ""),
            reason=str(data.get("reason") or ""),
            latency_ms=float(data["latency_ms"]) if data.get("latency_ms") is not None else None,
        )


class DedupCache:
    """Bounded in-memory deduplication + replay protection.

    Stores (message_id, nonce) pairs with TTL. Rejects duplicates and
    messages that arrive after their recorded expiry window.
    """

    def __init__(self, *, max_entries: int = 4096, default_ttl: float = 300.0):
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self._seen: Dict[str, Tuple[float, Set[str]]] = {}
        self._stats = {"hits": 0, "misses": 0, "evictions": 0, "replays": 0}

    def _purge(self) -> None:
        now = time.time()
        dead = [mid for mid, (exp, _) in self._seen.items() if exp <= now]
        for mid in dead:
            del self._seen[mid]
            self._stats["evictions"] += 1
        while len(self._seen) >= self.max_entries:
            oldest = min(self._seen.items(), key=lambda x: x[1][0])
            del self._seen[oldest[0]]
            self._stats["evictions"] += 1

    def check_and_record(self, message_id: str, nonce: str, *, ttl: Optional[float] = None) -> bool:
        """Return True if this is a NEW (non-duplicate) message; False if replay/dup."""
        self._purge()
        entry = self._seen.get(message_id)
        if entry is not None:
            exp, nonces = entry
            if nonce in nonces or time.time() < exp:
                self._stats["hits"] += 1
                self._stats["replays"] += 1
                return False
        ttl = ttl if ttl is not None else self.default_ttl
        nonces = {nonce}
        if entry is not None:
            nonces |= entry[1]
        self._seen[message_id] = (time.time() + ttl, nonces)
        self._stats["misses"] += 1
        return True

    def seen(self, message_id: str) -> bool:
        self._purge()
        return message_id in self._seen

    def stats(self) -> Dict[str, int]:
        return dict(self._stats)


@dataclass
class PeerHealth:
    """Reachability and delivery outcome tracking for a peer / next-hop."""

    peer_id: str
    last_success_at: Optional[float] = None
    last_failure_at: Optional[float] = None
    last_contact_at: Optional[float] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_successes: int = 0
    total_failures: int = 0
    avg_latency_ms: Optional[float] = None
    last_failure_reason: str = ""
    unreachable_confirmed: bool = False
    temporary_loss_until: float = 0.0

    def record_success(self, latency_ms: Optional[float] = None) -> None:
        now = time.time()
        self.last_success_at = now
        self.last_contact_at = now
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.total_successes += 1
        self.unreachable_confirmed = False
        self.temporary_loss_until = 0.0
        if latency_ms is not None:
            if self.avg_latency_ms is None:
                self.avg_latency_ms = latency_ms
            else:
                self.avg_latency_ms = 0.7 * self.avg_latency_ms + 0.3 * latency_ms

    def record_failure(self, reason: str, *, confirm_unreachable: bool = False) -> None:
        now = time.time()
        self.last_failure_at = now
        self.last_contact_at = now
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.total_failures += 1
        self.last_failure_reason = reason
        if confirm_unreachable or self.consecutive_failures >= 5:
            self.unreachable_confirmed = True
        else:
            backoff = min(60.0, 2.0 ** min(self.consecutive_failures, 5))
            self.temporary_loss_until = now + backoff

    @property
    def is_temporarily_lost(self) -> bool:
        return time.time() < self.temporary_loss_until and not self.unreachable_confirmed

    @property
    def is_reachable(self) -> bool:
        if self.unreachable_confirmed:
            return False
        if self.is_temporarily_lost:
            return False
        return self.consecutive_failures < 3 or self.last_success_at is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "last_contact_at": self.last_contact_at,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "avg_latency_ms": self.avg_latency_ms,
            "last_failure_reason": self.last_failure_reason,
            "unreachable_confirmed": self.unreachable_confirmed,
            "temporary_loss_until": self.temporary_loss_until,
            "is_temporarily_lost": self.is_temporarily_lost,
            "is_reachable": self.is_reachable,
        }


class PeerHealthTracker:
    """Track peer reachability without letting unauthenticated peers manipulate scores."""

    def __init__(self):
        self._peers: Dict[str, PeerHealth] = {}

    def get(self, peer_id: str) -> PeerHealth:
        if peer_id not in self._peers:
            self._peers[peer_id] = PeerHealth(peer_id=peer_id)
        return self._peers[peer_id]

    def record_success(self, peer_id: str, latency_ms: Optional[float] = None) -> None:
        self.get(peer_id).record_success(latency_ms)

    def record_failure(self, peer_id: str, reason: str, *, confirm_unreachable: bool = False) -> None:
        self.get(peer_id).record_failure(reason, confirm_unreachable=confirm_unreachable)

    def list_peers(self) -> Dict[str, Dict[str, Any]]:
        return {pid: p.to_dict() for pid, p in self._peers.items()}

    def clear(self) -> None:
        self._peers.clear()


@dataclass
class DeliveryOutcome:
    """Result of an attempt to deliver a message along a path."""

    state: DeliveryState
    message_id: str
    route_id: Optional[str] = None
    transport: Optional[str] = None
    attempts: int = 0
    hop_acks: int = 0
    destination_ack: bool = False
    failure_reason: str = ""
    selected_routes: list = field(default_factory=list)
    rejected_routes: list = field(default_factory=list)
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "message_id": self.message_id,
            "route_id": self.route_id,
            "transport": self.transport,
            "attempts": self.attempts,
            "hop_acks": self.hop_acks,
            "destination_ack": self.destination_ack,
            "failure_reason": self.failure_reason,
            "selected_routes": list(self.selected_routes),
            "rejected_routes": list(self.rejected_routes),
            "latency_ms": self.latency_ms,
            "details": dict(self.details),
            "result_kind": self._legacy_kind(),
            "send_accepted": self.state in (
                DeliveryState.ACCEPTED, DeliveryState.FORWARDED, DeliveryState.DELIVERED
            ),
            "recipient_acknowledged": self.destination_ack,
            "application_delivered": self.state == DeliveryState.DELIVERED and self.destination_ack,
        }

    def _legacy_kind(self) -> str:
        if self.state == DeliveryState.DELIVERED:
            return "application_delivered" if self.destination_ack else "recipient_acknowledged"
        if self.state == DeliveryState.FORWARDED:
            return "send_accepted"
        if self.state == DeliveryState.ACCEPTED:
            return "send_accepted"
        if self.state == DeliveryState.FAILED:
            return "failed"
        return "unknown"
