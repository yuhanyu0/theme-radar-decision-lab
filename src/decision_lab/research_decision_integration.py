from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any

from .decision import compile_decision
from .ledger import canonical_hash
from .linkage import LinkageResult
from .playbooks import PlaybookRouting, route_playbooks
from .research_decision_readiness import (
    ResearchDecisionReadinessAssessment,
    ResearchDecisionReadinessStatus,
    assess_research_decision_readiness,
)
from .research_execution import ResearchMode
from .research_execution_archive import ResearchDossierArchiveRecord
from .tape import TapeAssessment


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




@dataclass(frozen=True)
class ResearchDecisionRoutingInputs:
    fundamentals_intact: bool = False
    true_catalyst: bool = False
    breakout_confirmed: bool = False
    squeeze_confirmed: bool = False
    stable_regime: bool = False
    overheated_without_upgrade: bool = False
    pair_divergence: bool = False
    structural_repricing: bool = False
    world_confidence: str = "unknown"


@dataclass(frozen=True)
class ResearchGatedDecisionCompilation:
    admission: ResearchDecisionAdmission
    tape: TapeAssessment
    routing: PlaybookRouting
    decision: dict[str, Any]


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



def compile_research_gated_decision(
    *,
    records: Sequence[ResearchDossierArchiveRecord],
    readiness: ResearchDecisionReadinessAssessment,
    ticker: str,
    tape: TapeAssessment,
    theme_key: bool,
    routing_inputs: ResearchDecisionRoutingInputs,
    decision_id: str,
    market_asof: str,
    theme_state: str,
    company_state: str,
    strongest_reason_not_to_trade: str,
    model_version: str,
    config_payload: Any,
    dynamic_universe_layer: str | None = None,
    company_thesis: str | None = None,
    linkage: LinkageResult | None = None,
    radar_run_id: str | None = None,
    radar_source_commit: str | None = None,
    world_raw: str | None = None,
    world_calibrated: str | None = None,
    max_permission: str | float | None = None,
    entry_condition: str | None = None,
    invalidation: str | None = None,
    evidence_refs: list[str] | None = None,
    source_timestamps: dict[str, str | None] | None = None,
) -> ResearchGatedDecisionCompilation:
    admission = evaluate_research_decision_admission(
        records,
        readiness,
        ticker,
    )
    if admission.status is not ResearchDecisionAdmissionStatus.ADMITTED:
        raise ValueError("research admission is not ADMITTED")
    if not isinstance(tape, TapeAssessment):
        raise TypeError("tape must be TapeAssessment")
    if not isinstance(theme_key, bool):
        raise TypeError("theme_key must be bool")
    if not isinstance(routing_inputs, ResearchDecisionRoutingInputs):
        raise TypeError(
            "routing_inputs must be ResearchDecisionRoutingInputs"
        )

    routing = route_playbooks(
        theme_key=theme_key,
        tape_state=tape.state,
        tape_stage=tape.stage,
        fundamentals_intact=routing_inputs.fundamentals_intact,
        true_catalyst=routing_inputs.true_catalyst,
        breakout_confirmed=routing_inputs.breakout_confirmed,
        squeeze_confirmed=routing_inputs.squeeze_confirmed,
        stable_regime=routing_inputs.stable_regime,
        overheated_without_upgrade=(
            routing_inputs.overheated_without_upgrade
        ),
        pair_divergence=routing_inputs.pair_divergence,
        structural_repricing=routing_inputs.structural_repricing,
        world_confidence=routing_inputs.world_confidence,
    )
    decision = compile_decision(
        decision_id=decision_id,
        market_asof=market_asof,
        theme=admission.theme_id,
        ticker=admission.ticker,
        theme_state=theme_state,
        theme_key=theme_key,
        company_state=company_state,
        tape=tape,
        routing=routing,
        strongest_reason_not_to_trade=strongest_reason_not_to_trade,
        model_version=model_version,
        config_payload=config_payload,
        dynamic_universe_layer=dynamic_universe_layer,
        company_thesis=company_thesis,
        linkage=linkage,
        radar_run_id=radar_run_id,
        radar_source_commit=radar_source_commit,
        world_raw=world_raw,
        world_calibrated=world_calibrated,
        world_confidence=routing_inputs.world_confidence,
        max_permission=max_permission,
        entry_condition=entry_condition,
        invalidation=invalidation,
        evidence_refs=evidence_refs,
        source_timestamps=source_timestamps,
    )
    return ResearchGatedDecisionCompilation(
        admission=admission,
        tape=tape,
        routing=routing,
        decision=decision,
    )
