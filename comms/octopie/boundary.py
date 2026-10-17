"""Isolated Octopie integration boundary for Aurora.

Modes: disabled | observe_only | enforce
Does NOT modify mesh_join, discovery, or routing policy.
Transport success remains independent of trust.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from .contract import (
    CONTRACT_VERSION, AdmissionDecision, ContractError, DecisionOutcome,
    MembershipSnapshot, NodeRevocation, TrustOutcome, parse_decision,
)

logger = logging.getLogger("aurora.comms.octopie")


@dataclass
class BoundaryConfig:
    mode: str = "disabled"
    decision_max_age_seconds: float = 600.0

    @classmethod
    def from_env(cls) -> "BoundaryConfig":
        mode = (os.getenv("AURORA_OCTOPIE_MODE") or "disabled").strip().lower()
        if mode not in ("disabled", "observe_only", "enforce"):
            mode = "disabled"
        try:
            max_age = float(os.getenv("AURORA_OCTOPIE_DECISION_MAX_AGE", "600"))
        except ValueError:
            max_age = 600.0
        return cls(mode=mode, decision_max_age_seconds=max_age)


@dataclass
class BoundaryStatus:
    mode: str
    contract_version: str
    cached_admitted: int
    revoked: int
    last_error: str = ""
    decisions_accepted: int = 0
    decisions_rejected: int = 0

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "contract_version": self.contract_version,
            "cached_admitted": self.cached_admitted,
            "revoked": self.revoked,
            "last_error": self.last_error,
            "decisions_accepted": self.decisions_accepted,
            "decisions_rejected": self.decisions_rejected,
            "octopie_enabled": self.mode != "disabled",
        }


class OctopieBoundary:
    def __init__(self, config: Optional[BoundaryConfig] = None):
        self.config = config or BoundaryConfig()
        self._admitted: Dict[str, AdmissionDecision] = {}
        self._revoked: Set[str] = set()
        self._seen_correlations: Set[str] = set()
        self._accepted = 0
        self._rejected = 0
        self._last_error = ""

    def ingest_decision(self, raw: str | dict, now: Optional[float] = None) -> tuple[bool, str]:
        now = now if now is not None else time.time()
        if self.config.mode == "disabled":
            self._rejected += 1
            self._last_error = "octopie_disabled"
            return False, "octopie_disabled"
        try:
            decision = parse_decision(raw)
        except (ContractError, KeyError, ValueError, TypeError) as e:
            self._rejected += 1
            code = getattr(e, "code", "malformed_decision")
            self._last_error = str(e)
            logger.info("octopie decision rejected: %s", e)
            return False, code
        if decision.node_id in self._revoked:
            self._rejected += 1
            self._last_error = "node_revoked"
            return False, "node_revoked"
        if decision.is_expired(now):
            self._rejected += 1
            self._last_error = "decision_expired"
            return False, "decision_expired"
        if decision.decided_at > now + 60:
            self._rejected += 1
            self._last_error = "decision_from_future"
            return False, "decision_from_future"
        age = now - decision.decided_at
        if age > self.config.decision_max_age_seconds:
            self._rejected += 1
            self._last_error = "decision_too_old"
            return False, "decision_too_old"
        if decision.correlation_id in self._seen_correlations:
            self._accepted += 1
            return True, "duplicate_idempotent"
        self._seen_correlations.add(decision.correlation_id)
        if decision.outcome == DecisionOutcome.REVOKE:
            self._apply_revocation(decision.node_id)
            self._accepted += 1
            return True, "revoked"
        if decision.outcome != DecisionOutcome.ADMIT:
            self._accepted += 1
            return True, f"outcome_{decision.outcome.value}"
        if decision.trust_outcome != TrustOutcome.ADMITTED_ACTIVE:
            self._rejected += 1
            self._last_error = "trust_outcome_not_active"
            return False, "trust_outcome_not_active"
        if self.config.mode == "observe_only":
            self._accepted += 1
            return True, "observed_not_enforced"
        self._admitted[decision.node_id] = decision
        self._accepted += 1
        return True, "admitted"

    def ingest_revocation(self, raw: str | dict) -> tuple[bool, str]:
        if self.config.mode == "disabled":
            return False, "octopie_disabled"
        try:
            if isinstance(raw, str):
                import json
                raw = json.loads(raw)
            rev = NodeRevocation.from_dict(raw)
        except (ContractError, KeyError, ValueError, TypeError) as e:
            self._last_error = str(e)
            return False, getattr(e, "code", "malformed_revocation")
        self._apply_revocation(rev.node_id)
        return True, "revoked"

    def apply_membership_snapshot(self, raw: str | dict) -> tuple[bool, str]:
        if self.config.mode != "enforce":
            return False, "not_in_enforce_mode"
        try:
            if isinstance(raw, str):
                import json
                raw = json.loads(raw)
            snap = MembershipSnapshot.from_dict(raw)
        except (ContractError, KeyError, ValueError, TypeError) as e:
            return False, getattr(e, "code", "malformed_snapshot")
        new_cache: Dict[str, AdmissionDecision] = {}
        for nid in snap.admitted_node_ids:
            if nid in self._revoked:
                continue
            if nid in self._admitted:
                new_cache[nid] = self._admitted[nid]
        self._admitted = new_cache
        return True, "snapshot_applied"

    def _apply_revocation(self, node_id: str) -> None:
        self._revoked.add(node_id)
        self._admitted.pop(node_id, None)

    def is_trusted(self, node_id: str, now: Optional[float] = None) -> bool:
        if self.config.mode != "enforce":
            return False
        if node_id in self._revoked:
            return False
        dec = self._admitted.get(node_id)
        if dec is None:
            return False
        now = now if now is not None else time.time()
        if dec.is_expired(now):
            self._admitted.pop(node_id, None)
            return False
        return True

    def trusted_nodes(self, now: Optional[float] = None) -> List[str]:
        now = now if now is not None else time.time()
        return [nid for nid in list(self._admitted) if self.is_trusted(nid, now)]

    def status(self) -> BoundaryStatus:
        return BoundaryStatus(
            mode=self.config.mode,
            contract_version=CONTRACT_VERSION,
            cached_admitted=len(self._admitted),
            revoked=len(self._revoked),
            last_error=self._last_error,
            decisions_accepted=self._accepted,
            decisions_rejected=self._rejected,
        )

    def transport_success_grants_trust(self) -> bool:
        return False
