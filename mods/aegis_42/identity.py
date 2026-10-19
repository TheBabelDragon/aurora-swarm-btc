"""Node and worker identities, scoped capabilities, trust records, revocation."""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field


class Capability(BaseModel):
    name: str
    scope: str = "local"  # local | mesh | operator
    granted_by: Optional[str] = None
    granted_at: float = Field(default_factory=time.time)
    expires_at: Optional[float] = None
    revocable: bool = True

    def is_valid(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        if self.expires_at is not None and now > self.expires_at:
            return False
        return True


class TrustRecord(BaseModel):
    subject_id: str
    trust_level: str = "untrusted"  # untrusted | provisional | trusted | operator
    attested_by: Optional[str] = None
    reason: str = ""
    ts: float = Field(default_factory=time.time)
    revoked: bool = False
    revoked_at: Optional[float] = None


class IdentityRecord(BaseModel):
    identity_id: str
    node_id: Optional[str] = None
    kind: str = "worker"  # worker | agent | peer | operator | system
    capabilities: Dict[str, Capability] = Field(default_factory=dict)
    trust: TrustRecord
    created_at: float = Field(default_factory=time.time)
    last_seen: float = Field(default_factory=time.time)
    metadata: Dict[str, str] = Field(default_factory=dict)


class IdentityRegistry:
    """In-memory identity + capability store with explicit revocation."""

    def __init__(self):
        self._identities: Dict[str, IdentityRecord] = {}
        self._revoked: Set[str] = set()

    def register(
        self,
        identity_id: str,
        *,
        node_id: Optional[str] = None,
        kind: str = "worker",
        capabilities: Optional[List[str]] = None,
        trust_level: str = "untrusted",
        metadata: Optional[Dict[str, str]] = None,
    ) -> IdentityRecord:
        if identity_id in self._revoked:
            raise ValueError(f"Identity {identity_id} is revoked")
        caps = {}
        for c in (capabilities or []):
            caps[c] = Capability(name=c, granted_by="system")
        rec = IdentityRecord(
            identity_id=identity_id,
            node_id=node_id,
            kind=kind,
            capabilities=caps,
            trust=TrustRecord(subject_id=identity_id, trust_level=trust_level),
            metadata=metadata or {},
        )
        self._identities[identity_id] = rec
        return rec

    def get(self, identity_id: str) -> Optional[IdentityRecord]:
        if identity_id in self._revoked:
            return None
        return self._identities.get(identity_id)

    def capabilities_of(self, identity_id: str) -> Set[str]:
        rec = self.get(identity_id)
        if not rec:
            return set()
        now = time.time()
        return {n for n, c in rec.capabilities.items() if c.is_valid(now)}

    def is_trusted(self, identity_id: str) -> bool:
        rec = self.get(identity_id)
        if not rec or rec.trust.revoked:
            return False
        return rec.trust.trust_level in ("trusted", "operator")

    def grant_capability(
        self,
        identity_id: str,
        capability: str,
        *,
        granted_by: str,
        expires_at: Optional[float] = None,
    ) -> bool:
        rec = self.get(identity_id)
        if not rec:
            return False
        # Only operator / system may grant
        if granted_by not in ("operator", "system", "aegis") and not self.is_trusted(granted_by):
            return False
        rec.capabilities[capability] = Capability(
            name=capability,
            granted_by=granted_by,
            expires_at=expires_at,
        )
        rec.last_seen = time.time()
        return True

    def revoke_capability(self, identity_id: str, capability: str) -> bool:
        rec = self.get(identity_id)
        if not rec:
            return False
        if capability in rec.capabilities:
            del rec.capabilities[capability]
            return True
        return False

    def revoke_identity(self, identity_id: str, reason: str = "") -> bool:
        rec = self._identities.get(identity_id)
        if rec:
            rec.trust.revoked = True
            rec.trust.revoked_at = time.time()
            rec.trust.reason = reason or rec.trust.reason
        self._revoked.add(identity_id)
        return True

    def list_identities(self) -> List[IdentityRecord]:
        return [r for iid, r in self._identities.items() if iid not in self._revoked]

    def touch(self, identity_id: str) -> None:
        rec = self.get(identity_id)
        if rec:
            rec.last_seen = time.time()
