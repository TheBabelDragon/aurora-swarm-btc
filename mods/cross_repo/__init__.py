"""Cross-repository API contracts for the BabelDragon Chimera path.

Physical observations → CANtheon → MetaField → TensorGate → MultiFlow → Aurora

This module defines JSON-compatible typed envelopes used at repository
boundaries. It does not vendor sibling repositories. MultiFlow is optional.
"""

from .contracts import (
    CONTRACT_CATALOG,
    ExecutionAcknowledgement,
    ExecutionRequest,
    HealthStatus,
    SchedulingPlanEnvelope,
    SchedulingRequestEnvelope,
)
from .evidence_bridge import ingest_decision_evidence, link_evidence_chain
from .multiflow_client import MultiFlowClient, MultiFlowClientStatus

__all__ = [
    "CONTRACT_CATALOG",
    "ExecutionAcknowledgement",
    "ExecutionRequest",
    "HealthStatus",
    "SchedulingPlanEnvelope",
    "SchedulingRequestEnvelope",
    "ingest_decision_evidence",
    "link_evidence_chain",
    "MultiFlowClient",
    "MultiFlowClientStatus",
]
