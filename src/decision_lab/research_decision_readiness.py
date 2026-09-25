from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from enum import Enum

from .ledger import canonical_hash
from .research_execution import (
    ResearchDossierStatus,
    ResearchExecutionClosure,
)
from .research_execution_archive import ResearchDossierArchiveRecord
from .research_progression import evaluate_research_progression

READINESS_POLICY_VERSION = "0.1"


class ResearchDecisionReadinessStatus(str, Enum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    INDETERMINATE = "INDETERMINATE"


class ResearchDecisionReadinessGate(str, Enum):
    CANDIDATE_IS_LEAF = "CANDIDATE_IS_LEAF"
    DOSSIER_COMPLETE = "DOSSIER_COMPLETE"
    EXECUTION_CLOSED = "EXECUTION_CLOSED"
    NO_UNSATISFIED_REQUIREMENTS = "NO_UNSATISFIED_REQUIREMENTS"
    NO_UNRESOLVED_FINDINGS = "NO_UNRESOLVED_FINDINGS"
    GLOBAL_SOURCE_MINIMUM_MET = "GLOBAL_SOURCE_MINIMUM_MET"
    COMPANY_SOURCE_MINIMUMS_MET = "COMPANY_SOURCE_MINIMUMS_MET"
    LINEAGE_COMPLETE = "LINEAGE_COMPLETE"
    UNIQUE_OBSERVED_LEAF = "UNIQUE_OBSERVED_LEAF"


_GATE_ORDER = (
    ResearchDecisionReadinessGate.CANDIDATE_IS_LEAF,
    ResearchDecisionReadinessGate.DOSSIER_COMPLETE,
    ResearchDecisionReadinessGate.EXECUTION_CLOSED,
    ResearchDecisionReadinessGate.NO_UNSATISFIED_REQUIREMENTS,
    ResearchDecisionReadinessGate.NO_UNRESOLVED_FINDINGS,
    ResearchDecisionReadinessGate.GLOBAL_SOURCE_MINIMUM_MET,
    ResearchDecisionReadinessGate.COMPANY_SOURCE_MINIMUMS_MET,
    ResearchDecisionReadinessGate.LINEAGE_COMPLETE,
    ResearchDecisionReadinessGate.UNIQUE_OBSERVED_LEAF,
)

_LOCAL_GATES = frozenset(_GATE_ORDER[:7])
_DETERMINACY_GATES = frozenset(_GATE_ORDER[7:])

_POLICY_PAYLOAD = {
    "version": READINESS_POLICY_VERSION,
    "gate_order": tuple(gate.value for gate in _GATE_ORDER),
    "status_precedence": (
        "local_failure->NOT_READY",
        "determinacy_failure->INDETERMINATE",
        "otherwise->READY",
    ),
    "ready_meaning": "research-ready for downstream decision analysis",
    "trading_permission": False,
}
READINESS_POLICY_HASH = canonical_hash(_POLICY_PAYLOAD)

_LIMITATIONS = (
    "READY means research-ready for downstream decision analysis, not trading permission",
    "readiness is relative to the supplied validated archive set",
    "contradictions are surfaced but do not automatically block readiness",
    "Tape, playbook, market freshness, and execution conditions are not evaluated",
    "no canonical fork or root is selected",
)


@dataclass(frozen=True)
class ResearchDecisionReadinessGateResult:
    gate: ResearchDecisionReadinessGate
    passed: bool


@dataclass(frozen=True)
class ResearchDecisionReadinessCompanyCaution:
    ticker: str
    caution: str


@dataclass(frozen=True)
class ResearchDecisionReadinessAssessment:
    policy_version: str
    policy_hash: str
    progression_report_hash: str
    work_order_archive_record_hash: str
    work_order_hash: str
    candidate_archive_record_hash: str
    status: ResearchDecisionReadinessStatus
    candidate_sufficient: bool
    selection_determinate: bool
    gate_results: tuple[ResearchDecisionReadinessGateResult, ...]
    competing_leaf_archive_record_hashes: tuple[str, ...]
    contradictions_present: bool
    execution_reopen_count: int
    completion_loss_count: int
    company_cautions: tuple[ResearchDecisionReadinessCompanyCaution, ...]
    limitations: tuple[str, ...]
    readiness_assessment_hash: str


def _assessment_payload_without_hash(
    assessment: ResearchDecisionReadinessAssessment,
) -> dict[str, object]:
    payload = asdict(assessment)
    payload.pop("readiness_assessment_hash")
    return payload


def _status_from_gates(
    gate_results: tuple[ResearchDecisionReadinessGateResult, ...],
) -> tuple[
    ResearchDecisionReadinessStatus,
    bool,
    bool,
]:
    local_passed = all(
        item.passed
        for item in gate_results
        if item.gate in _LOCAL_GATES
    )
    determinacy_passed = all(
        item.passed
        for item in gate_results
        if item.gate in _DETERMINACY_GATES
    )
    if not local_passed:
        status = ResearchDecisionReadinessStatus.NOT_READY
    elif not determinacy_passed:
        status = ResearchDecisionReadinessStatus.INDETERMINATE
    else:
        status = ResearchDecisionReadinessStatus.READY
    return status, local_passed, determinacy_passed


def assess_research_decision_readiness(
    records: Sequence[ResearchDossierArchiveRecord],
    candidate_archive_record_hash: str,
) -> ResearchDecisionReadinessAssessment:
    report = evaluate_research_progression(records)

    candidate_snapshots = tuple(
        item
        for item in report.snapshots
        if item.archive_record_hash == candidate_archive_record_hash
    )
    if not candidate_snapshots:
        raise ValueError(
            "research decision readiness candidate is not present"
        )
    if len(candidate_snapshots) != 1:
        raise ValueError(
            "research decision readiness candidate is inconsistent"
        )
    candidate = candidate_snapshots[0]

    candidate_is_leaf = candidate_archive_record_hash in report.leaves
    matching_trajectories = tuple(
        trajectory
        for trajectory in report.trajectories
        if trajectory.leaf_archive_record_hash
        == candidate_archive_record_hash
    )
    if candidate_is_leaf:
        if len(matching_trajectories) != 1:
            raise ValueError(
                "research decision readiness candidate trajectory is inconsistent"
            )
        candidate_trajectory = matching_trajectories[0]
        lineage_complete = candidate_trajectory.lineage_complete
        execution_reopen_count = candidate_trajectory.execution_reopen_count
        completion_loss_count = candidate_trajectory.completion_loss_count
    else:
        candidate_trajectory = None
        lineage_complete = False
        execution_reopen_count = 0
        completion_loss_count = 0

    competing_leaves = tuple(
        sorted(
            archive_hash
            for archive_hash in report.leaves
            if archive_hash != candidate_archive_record_hash
        )
    )
    unique_observed_leaf = (
        report.leaves == (candidate_archive_record_hash,)
    )

    basic_pass = {
        ResearchDecisionReadinessGate.CANDIDATE_IS_LEAF: (
            candidate_is_leaf
        ),
        ResearchDecisionReadinessGate.DOSSIER_COMPLETE: (
            candidate.status is ResearchDossierStatus.COMPLETE
        ),
        ResearchDecisionReadinessGate.EXECUTION_CLOSED: (
            candidate.closure is ResearchExecutionClosure.CLOSED
        ),
        ResearchDecisionReadinessGate.NO_UNSATISFIED_REQUIREMENTS: (
            not candidate.burden.unsatisfied_requirements
        ),
        ResearchDecisionReadinessGate.NO_UNRESOLVED_FINDINGS: (
            not candidate.burden.unresolved_finding_ids
        ),
        ResearchDecisionReadinessGate.GLOBAL_SOURCE_MINIMUM_MET: (
            candidate.burden.independent_source_deficit == 0
        ),
        ResearchDecisionReadinessGate.COMPANY_SOURCE_MINIMUMS_MET: all(
            item.independent_source_deficit == 0
            for item in candidate.burden.company_burdens
        ),
        ResearchDecisionReadinessGate.LINEAGE_COMPLETE: (
            lineage_complete
        ),
        ResearchDecisionReadinessGate.UNIQUE_OBSERVED_LEAF: (
            unique_observed_leaf
        ),
    }
    gate_results = tuple(
        ResearchDecisionReadinessGateResult(
            gate=gate,
            passed=basic_pass[gate],
        )
        for gate in _GATE_ORDER
    )
    status, candidate_sufficient, selection_determinate = _status_from_gates(
        gate_results
    )

    company_cautions = tuple(
        ResearchDecisionReadinessCompanyCaution(
            ticker=company.ticker,
            caution=caution,
        )
        for company in candidate.burden.company_burdens
        for caution in company.cautions
    )
    company_cautions = tuple(
        sorted(
            company_cautions,
            key=lambda item: (item.ticker, item.caution),
        )
    )

    seed = ResearchDecisionReadinessAssessment(
        policy_version=READINESS_POLICY_VERSION,
        policy_hash=READINESS_POLICY_HASH,
        progression_report_hash=report.progression_report_hash,
        work_order_archive_record_hash=(
            report.work_order_archive_record_hash
        ),
        work_order_hash=report.work_order_hash,
        candidate_archive_record_hash=candidate_archive_record_hash,
        status=status,
        candidate_sufficient=candidate_sufficient,
        selection_determinate=selection_determinate,
        gate_results=gate_results,
        competing_leaf_archive_record_hashes=competing_leaves,
        contradictions_present=candidate.burden.contradictions_present,
        execution_reopen_count=execution_reopen_count,
        completion_loss_count=completion_loss_count,
        company_cautions=company_cautions,
        limitations=_LIMITATIONS,
        readiness_assessment_hash="0" * 64,
    )
    return replace(
        seed,
        readiness_assessment_hash=canonical_hash(
            _assessment_payload_without_hash(seed)
        ),
    )
