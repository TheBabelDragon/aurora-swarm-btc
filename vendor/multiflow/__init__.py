"""MultiFlow — vendored classical core. Upstream: https://github.com/TheBabelDragon/MultiFlow"""
from multiflow.domain.models import (
    TimeWindow,
    ResourceType,
    Resource,
    Requirement,
    Task,
    Severity,
    Assignment,
    Schedule,
    ObjectiveDirection,
    Objective,
    SchedulingProblem,
    SolutionScore,
    CandidateSolution,
    ConstraintResult,
    ValidationResult,
    ScheduleConflict,
)
from multiflow.solver.classical import ClassicalSolver
from multiflow.solver.interface import Solver
from multiflow.solver.result import SolverResult, SolverStatus
from multiflow.solver.registry import get_solver, available_solvers
from multiflow.validation.validator import Validator
from multiflow.arbitration.conflicts import ConflictDetector, Arbitrator
from multiflow.constraints.base import Constraint, EvaluationContext
from multiflow.constraints.builtin import (
    NoOverlapConstraint,
    AvailabilityConstraint,
    CapabilityConstraint,
    CapacityConstraint,
    ProtectedWindowConstraint,
    PreferredResourceConstraint,
    TimeWindowConstraint,
)
from multiflow.serialization.io import load_problem, dump_problem
from multiflow.evidence import (
    OutcomeStatus,
    ConstraintVersion,
    DecisionEvidence,
    build_decision_evidence,
    attach_evidence_ref,
    check_evidence_schema,
    decision_record_to_evidence,
)
from multiflow.live import (
    SchedulingEvent,
    EventType,
    EventStore,
    ScheduleSnapshot,
    ScheduleFeatures,
    FeatureExtractor,
    CandidateScorer,
    DeterministicCandidateScorer,
    DecisionRecord,
    DecisionSource,
    OperationalMetrics,
    LiveEngine,
)

__version__ = "0.2.0"
__schema_prefix__ = "multiflow"

__all__ = [
    "TimeWindow", "ResourceType", "Resource", "Requirement", "Task", "Severity",
    "Assignment", "Schedule", "ObjectiveDirection", "Objective", "SchedulingProblem",
    "SolutionScore", "CandidateSolution", "ConstraintResult", "ValidationResult",
    "ScheduleConflict", "ClassicalSolver", "Solver", "SolverResult", "SolverStatus",
    "get_solver", "available_solvers", "Validator", "ConflictDetector", "Arbitrator",
    "Constraint", "EvaluationContext", "NoOverlapConstraint", "AvailabilityConstraint",
    "CapabilityConstraint", "CapacityConstraint", "ProtectedWindowConstraint",
    "PreferredResourceConstraint", "TimeWindowConstraint", "load_problem", "dump_problem",
    "SchedulingEvent", "EventType", "EventStore", "ScheduleSnapshot", "ScheduleFeatures",
    "FeatureExtractor", "CandidateScorer", "DeterministicCandidateScorer",
    "DecisionRecord", "DecisionSource", "OperationalMetrics", "LiveEngine",
    "OutcomeStatus", "ConstraintVersion", "DecisionEvidence", "build_decision_evidence",
    "attach_evidence_ref", "check_evidence_schema", "decision_record_to_evidence",
]
