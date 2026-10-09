"""Gateway capability advertisement and registry.

An advertisement is a claim that must be checked, not a trusted route.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("aurora.comms.routing.gateway")

SCHEMA_VERSION = "aurora.gateway.v1"
SIGN_FIELDS = (
    "schema_version", "node_id", "gateway_id", "capabilities",
    "supported_address_families", "supported_transports", "egress_enabled",
    "sequence", "issued_at", "expires_at",
)


def _mesh_secret() -> str:
    return (os.getenv("AURORA_MESH_SECRET") or "").strip()


def _canonical(body: Dict[str, Any]) -> bytes:
    slim = {k: body.get(k) for k in SIGN_FIELDS}
    return json.dumps(slim, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hmac_hex(key: bytes, msg: bytes) -> str:
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


@dataclass
class GatewayAdvertisement:
    schema_version: str = SCHEMA_VERSION
    node_id: str = ""
    gateway_id: str = ""
    capabilities: List[str] = field(default_factory=list)
    supported_address_families: List[str] = field(default_factory=lambda: ["ipv4"])
    supported_transports: List[str] = field(default_factory=lambda: ["mesh"])
    egress_enabled: bool = False
    policy_summary: str = ""
    sequence: int = 0
    issued_at: float = 0.0
    expires_at: float = 0.0
    signature: str = ""
    auth: str = "none"
    reachability: str = "advertised"
    last_health_at: Optional[float] = None
    from_ip: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "gateway_id": self.gateway_id,
            "capabilities": list(self.capabilities),
            "supported_address_families": list(self.supported_address_families),
            "supported_transports": list(self.supported_transports),
            "egress_enabled": self.egress_enabled,
            "policy_summary": self.policy_summary,
            "sequence": self.sequence,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature": self.signature,
            "auth": self.auth,
            "reachability": self.reachability,
            "last_health_at": self.last_health_at,
            "from_ip": self.from_ip,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GatewayAdvertisement":
        return cls(
            schema_version=str(d.get("schema_version") or SCHEMA_VERSION),
            node_id=str(d.get("node_id") or ""),
            gateway_id=str(d.get("gateway_id") or ""),
            capabilities=list(d.get("capabilities") or []),
            supported_address_families=list(d.get("supported_address_families") or ["ipv4"]),
            supported_transports=list(d.get("supported_transports") or ["mesh"]),
            egress_enabled=bool(d.get("egress_enabled")),
            policy_summary=str(d.get("policy_summary") or ""),
            sequence=int(d.get("sequence") or 0),
            issued_at=float(d.get("issued_at") or 0),
            expires_at=float(d.get("expires_at") or 0),
            signature=str(d.get("signature") or d.get("sig") or ""),
            auth=str(d.get("auth") or "none"),
            reachability=str(d.get("reachability") or "advertised"),
            last_health_at=d.get("last_health_at"),
            from_ip=d.get("from_ip"),
        )

    @property
    def is_expired(self) -> bool:
        if self.expires_at <= 0:
            return True
        return time.time() >= self.expires_at

    def sign(self, secret: Optional[str] = None) -> "GatewayAdvertisement":
        key = (secret if secret is not None else _mesh_secret()).encode()
        body = self.to_dict()
        if not key:
            self.auth = "none"
            self.signature = ""
            return self
        self.signature = _hmac_hex(key, _canonical(body))
        self.auth = "secret"
        return self

    def verify(self, secret: Optional[str] = None) -> Tuple[bool, str]:
        if self.schema_version != SCHEMA_VERSION:
            return False, "bad_schema"
        if not self.node_id or not self.gateway_id:
            return False, "missing_ids"
        if self.is_expired:
            return False, "expired"
        key_s = secret if secret is not None else _mesh_secret()
        require = os.getenv("AURORA_MESH_REQUIRE_AUTH", "0").lower() in ("1", "true", "yes", "on")
        if not key_s:
            if require:
                return False, "secret_required"
            return True, "unsigned"
        body = self.to_dict()
        expect = _hmac_hex(key_s.encode(), _canonical(body))
        if not self.signature or not hmac.compare_digest(expect, self.signature):
            return False, "bad_signature"
        return True, "secret"


class GatewayRegistry:
    def __init__(self, *, max_entries: int = 256):
        self._by_id: Dict[str, GatewayAdvertisement] = {}
        self._seq_floor: Dict[str, int] = {}
        self._max = max_entries
        self._stats = {"accepted": 0, "rejected": 0, "expired_removed": 0}

    def ingest(self, raw: Dict[str, Any], *, secret: Optional[str] = None, from_ip: Optional[str] = None) -> Tuple[bool, str, Optional[GatewayAdvertisement]]:
        try:
            adv = GatewayAdvertisement.from_dict(raw)
        except Exception as e:
            self._stats["rejected"] += 1
            return False, f"malformed:{e}", None
        if from_ip:
            adv.from_ip = from_ip
        ok, reason = adv.verify(secret=secret)
        if not ok:
            self._stats["rejected"] += 1
            return False, reason, None
        floor = self._seq_floor.get(adv.gateway_id, -1)
        if adv.sequence <= floor:
            self._stats["rejected"] += 1
            return False, "stale_sequence", None
        self._seq_floor[adv.gateway_id] = adv.sequence
        self._by_id[adv.gateway_id] = adv
        self._stats["accepted"] += 1
        self._trim()
        return True, reason, adv

    def _trim(self):
        if len(self._by_id) <= self._max:
            return
        ordered = sorted(self._by_id.values(), key=lambda a: a.expires_at)
        for adv in ordered[: len(self._by_id) - self._max]:
            self._by_id.pop(adv.gateway_id, None)

    def refresh(self) -> int:
        now = time.time()
        dead = [gid for gid, a in self._by_id.items() if a.expires_at <= now]
        for gid in dead:
            del self._by_id[gid]
            self._stats["expired_removed"] += 1
        return len(dead)

    def get(self, gateway_id: str) -> Optional[GatewayAdvertisement]:
        adv = self._by_id.get(gateway_id)
        if adv and adv.is_expired:
            del self._by_id[gateway_id]
            self._stats["expired_removed"] += 1
            return None
        return adv

    def list_gateways(self, *, egress_only: bool = False, reachable_only: bool = False) -> List[GatewayAdvertisement]:
        self.refresh()
        out = []
        for a in self._by_id.values():
            if egress_only and not a.egress_enabled:
                continue
            if reachable_only and a.reachability not in ("reachable", "degraded"):
                continue
            out.append(a)
        return out

    def mark_reachability(self, gateway_id: str, state: str):
        adv = self._by_id.get(gateway_id)
        if not adv:
            return
        if state not in ("advertised", "reachable", "degraded", "unavailable"):
            return
        adv.reachability = state
        adv.last_health_at = time.time()

    def build_local_advertisement(self, *, node_id: str, gateway_id: str, capabilities: Optional[List[str]] = None, egress_enabled: bool = False, ttl: float = 120.0, sequence: int = 1, transports: Optional[List[str]] = None) -> GatewayAdvertisement:
        now = time.time()
        adv = GatewayAdvertisement(
            node_id=node_id, gateway_id=gateway_id,
            capabilities=capabilities or ["mesh"],
            supported_transports=transports or ["mesh"],
            egress_enabled=egress_enabled, policy_summary="local-default",
            sequence=sequence, issued_at=now, expires_at=now + ttl,
        )
        adv.sign()
        return adv

    def stats(self) -> Dict[str, int]:
        return dict(self._stats)
