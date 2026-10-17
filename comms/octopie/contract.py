"""Minimal mirror of the octopie-aurora/1.0 contract for Aurora-side validation.

Kept independent so Aurora tests run without the Octopie package installed.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

CONTRACT_VERSION = "octopie-aurora/1.0"
SUPPORTED_VERSIONS = frozenset({CONTRACT_VERSION})


class TrustOutcome(str, Enum):
    OBSERVED_UNVERIFIED = "observed_unverified"
    AUTHENTICATED_NOT_AUTHORIZED = "authenticated_not_authorized"
    AUTHORIZED_NOT_ADMITTED = "authorized_not_admitted"
    ADMITTED_ACTIVE = "admitted_active"
    DEGRADED = "degraded"
    ISOLATED = "isolated"
    REVOKED = "revoked"
    REJECTED = "rejected"


class DecisionOutcome(str, Enum):
    ADMIT = "admit"
    REJECT = "reject"
    DEFER = "defer"
    REVOKE = "revoke"


class ContractError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _require_version(version: str) -> None:
    if version not in SUPPORTED_VERSIONS:
        raise ContractError(
            "incompatible_contract_version",
            f"got {version!r}, supported={sorted(SUPPORTED_VERSIONS)}",
        )


@dataclass(frozen=True)
class AdmissionDecision:
    node_id: str
    outcome: DecisionOutcome
    trust_outcome: TrustOutcome
    reason_code: str
    decided_at: float
    policy_version: str
    contract_version: str = CONTRACT_VERSION
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    expires_at: Optional[float] = None
    capabilities: List[str] = field(default_factory=list)

    def is_expired(self, now: Optional[float] = None) -> bool:
        if self.expires_at is None:
            return False
        return (now if now is not None else time.time()) >= self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        d["trust_outcome"] = self.trust_outcome.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AdmissionDecision":
        _require_version(str(d.get("contract_version", "")))
        return cls(
            node_id=str(d["node_id"]),
            outcome=DecisionOutcome(d["outcome"]),
            trust_outcome=TrustOutcome(d["trust_outcome"]),
            reason_code=str(d.get("reason_code", "")),
            decided_at=float(d["decided_at"]),
            policy_version=str(d.get("policy_version", "1")),
            contract_version=str(d["contract_version"]),
            correlation_id=str(d.get("correlation_id", uuid.uuid4())),
            expires_at=float(d["expires_at"]) if d.get("expires_at") is not None else None,
            capabilities=list(d.get("capabilities") or []),
        )


@dataclass(frozen=True)
class NodeRevocation:
    node_id: str
    revoked_at: float
    reason_code: str
    policy_version: str
    contract_version: str = CONTRACT_VERSION
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "NodeRevocation":
        _require_version(str(d.get("contract_version", "")))
        return cls(
            node_id=str(d["node_id"]),
            revoked_at=float(d["revoked_at"]),
            reason_code=str(d.get("reason_code", "")),
            policy_version=str(d.get("policy_version", "1")),
            contract_version=str(d["contract_version"]),
            correlation_id=str(d.get("correlation_id", uuid.uuid4())),
        )


@dataclass(frozen=True)
class MembershipSnapshot:
    snapshot_at: float
    admitted_node_ids: List[str]
    policy_version: str
    contract_version: str = CONTRACT_VERSION

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MembershipSnapshot":
        _require_version(str(d.get("contract_version", "")))
        return cls(
            snapshot_at=float(d["snapshot_at"]),
            admitted_node_ids=list(d.get("admitted_node_ids") or []),
            policy_version=str(d.get("policy_version", "1")),
            contract_version=str(d["contract_version"]),
        )


def parse_decision(raw: str | Dict[str, Any]) -> AdmissionDecision:
    data = json.loads(raw) if isinstance(raw, str) else raw
    return AdmissionDecision.from_dict(data)
