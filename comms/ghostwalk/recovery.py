"""Safe recovery proposals — proposals are not executed actions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    AUTHORIZED = "authorized"
    REJECTED = "rejected"
    EXECUTED = "executed"  # only if explicitly applied elsewhere
    EXPIRED = "expired"


@dataclass
class RecoveryProposal:
    proposal_id: str
    action: str
    subject_id: str
    trigger_evidence: List[str]
    expected_impact: str
    authorization_required: str
    rollback: str
    status: ProposalStatus = ProposalStatus.PROPOSED
    created_at: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "action": self.action,
            "subject_id": self.subject_id,
            "trigger_evidence": list(self.trigger_evidence),
            "expected_impact": self.expected_impact,
            "authorization_required": self.authorization_required,
            "rollback": self.rollback,
            "status": self.status.value,
            "created_at": self.created_at,
            "details": dict(self.details),
            "is_executed": self.status == ProposalStatus.EXECUTED,
            "note": "proposal_not_action",
        }


class RecoveryEngine:
    """Generate bounded proposals; does not auto-execute disruptive actions."""

    def __init__(self, *, local_node_id: str = "local"):
        self.local_node_id = local_node_id
        self._proposals: Dict[str, RecoveryProposal] = {}
        self._seq = 0

    def propose(
        self,
        action: str,
        subject_id: str,
        *,
        trigger_evidence: Optional[List[str]] = None,
        expected_impact: str = "",
        authorization_required: str = "operator",
        rollback: str = "manual_review",
        details: Optional[Dict[str, Any]] = None,
    ) -> RecoveryProposal:
        # Safety: peers cannot command their own trust rewrite
        if action in ("quarantine_peer", "revoke_peer", "rewrite_trust") and subject_id == self.local_node_id:
            authorization_required = "local_operator_only"

        self._seq += 1
        pid = f"rp-{self._seq}-{int(time.time())}"
        p = RecoveryProposal(
            proposal_id=pid,
            action=action,
            subject_id=subject_id,
            trigger_evidence=list(trigger_evidence or []),
            expected_impact=expected_impact[:300],
            authorization_required=authorization_required,
            rollback=rollback[:200],
            status=ProposalStatus.PROPOSED,
            created_at=time.time(),
            details=dict(details or {}),
        )
        self._proposals[pid] = p
        if len(self._proposals) > 128:
            # drop oldest
            oldest = min(self._proposals.values(), key=lambda x: x.created_at)
            del self._proposals[oldest.proposal_id]
        return p

    def reject_unauthorized(self, proposal_id: str, reason: str = "unauthorized") -> Optional[RecoveryProposal]:
        p = self._proposals.get(proposal_id)
        if not p:
            return None
        p.status = ProposalStatus.REJECTED
        p.details["reject_reason"] = reason[:120]
        return p

    def list_proposals(self, *, active_only: bool = True) -> List[Dict[str, Any]]:
        out = []
        for p in self._proposals.values():
            if active_only and p.status not in (ProposalStatus.PROPOSED, ProposalStatus.AUTHORIZED):
                continue
            out.append(p.to_dict())
        return out
