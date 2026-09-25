from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from enum import Enum

from .ledger import canonical_hash
from .research_decision_readiness import (
    ResearchDecisionReadinessAssessment,
    ResearchDecisionReadinessStatus,
    assess_research_decision_readiness,
)
from .research_execution import ResearchMode
from .research_execution_archive import ResearchDossierArchiveRecord


class ResearchDecisionAdmissionStatus(str, Enum):
    ADMITTED = "ADMITTED"
    BLOCKED_NOT_READY = "BLOCKED_NOT_READY"
    BLOCKED_INDETERMINATE = "BLOCKED_INDETERMINATE"


@dataclass(frozen=True)
class ResearchDecisionAdmission:
    readiness_assessment_hash: str
    readiness_policy_hash: str
    progression_report_hash: str
    work_order_archive_record_hash: str
    work_order_hash: str
    candidate_archive_record_hash: str
    theme_id: str
    ticker: str
    status: ResearchDecisionAdmissionStatus
    reasons: tuple[str, ...]
    admission_hash: str


def _admission_payload_without_hash(
    admission: ResearchDecisionAdmission,
) -> dict[str, object]:
    payload = asdict(admission)
    payload.pop("admission_hash")
    return payload


def evaluate_research_decision_admission(
    records: Sequence[ResearchDossierArchiveRecord],
    readiness: ResearchDecisionReadinessAssessment,
    ticker: str,
) -> ResearchDecisionAdmission:
    if not isinstance(readiness, ResearchDecisionReadinessAssessment):
        raise TypeError(
            "readiness must be ResearchDecisionReadinessAssessment"
        )

    expected = assess_research_decision_readiness(
        records,
        readiness.candidate_archive_record_hash,
    )
    if readiness != expected:
        raise ValueError(
            "research decision readiness does not match supplied records"
        )

    candidate_matches = tuple(
        record
        for record in records
        if record.archive_record_hash
        == readiness.candidate_archive_record_hash
    )
    if len(candidate_matches) != 1:
        raise ValueError(
            "research decision candidate archive is inconsistent"
        )
    candidate = candidate_matches[0]
    order = candidate.work_order_archive.work_order

    if order.research_mode is not ResearchMode.COMPANY_DEEP_DIVE:
        raise ValueError(
            "research decision admission requires company deep dive"
        )

    if not isinstance(ticker, str):
        raise TypeError("research decision ticker must be str")
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        raise ValueError("research decision ticker must be non-empty")

    target_tickers = tuple(target.ticker for target in order.targets)
    if normalized_ticker not in target_tickers:
        raise ValueError(
            "research decision ticker is not a work order target"
        )

    if readiness.status is ResearchDecisionReadinessStatus.READY:
        status = ResearchDecisionAdmissionStatus.ADMITTED
        reasons = (
            "research readiness is READY and target binding is exact",
        )
    elif readiness.status is ResearchDecisionReadinessStatus.NOT_READY:
        status = ResearchDecisionAdmissionStatus.BLOCKED_NOT_READY
        reasons = ("research readiness is NOT_READY",)
    elif (
        readiness.status
        is ResearchDecisionReadinessStatus.INDETERMINATE
    ):
        status = ResearchDecisionAdmissionStatus.BLOCKED_INDETERMINATE
        reasons = ("research readiness is INDETERMINATE",)
    else:
        raise ValueError("unsupported research decision readiness status")

    seed = ResearchDecisionAdmission(
        readiness_assessment_hash=readiness.readiness_assessment_hash,
        readiness_policy_hash=readiness.policy_hash,
        progression_report_hash=readiness.progression_report_hash,
        work_order_archive_record_hash=(
            readiness.work_order_archive_record_hash
        ),
        work_order_hash=readiness.work_order_hash,
        candidate_archive_record_hash=(
            readiness.candidate_archive_record_hash
        ),
        theme_id=order.theme_id,
        ticker=normalized_ticker,
        status=status,
        reasons=reasons,
        admission_hash="0" * 64,
    )
    return replace(
        seed,
        admission_hash=canonical_hash(
            _admission_payload_without_hash(seed)
        ),
    )
