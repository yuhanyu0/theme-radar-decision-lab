from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from enum import Enum

from .ledger import canonical_hash
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
    RESEARCH_NOT_READY = "RESEARCH_NOT_READY"
    RESEARCH_INDETERMINATE = "RESEARCH_INDETERMINATE"
    RESEARCH_SCOPE_MISMATCH = "RESEARCH_SCOPE_MISMATCH"
    ADMITTED = "ADMITTED"


@dataclass(frozen=True)
class DecisionRoutingInputs:
    theme_key: bool
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
class ResearchDecisionIntegration:
    readiness_assessment: ResearchDecisionReadinessAssessment
    research_mode: ResearchMode
    work_order_theme_id: str
    work_order_target_tickers: tuple[str, ...]
    requested_theme: str
    requested_ticker: str
    admission_status: ResearchDecisionAdmissionStatus
    scope_mismatch_reasons: tuple[str, ...]
    tape: TapeAssessment
    tape_hash: str
    routing_inputs: DecisionRoutingInputs
    routing_inputs_hash: str
    routing: PlaybookRouting
    routing_hash: str
    market_action: str
    admitted_action: str | None
    limitations: tuple[str, ...]
    integration_hash: str


_LIMITATIONS = (
    "research admission is separate from market action",
    "market action is not brokerage execution",
    "playbook scores remain uncalibrated unless the router says otherwise",
    "no research branch is selected by this integration layer",
)


def _routing_payload(routing: PlaybookRouting) -> dict[str, object]:
    return {
        "raw_scores": dict(routing.raw_scores),
        "normalized_scores": dict(routing.normalized_scores),
        "selected_playbook": routing.selected_playbook,
        "action": routing.action,
        "probability_is_calibrated": routing.probability_is_calibrated,
        "rationale": routing.rationale,
    }


def _integration_payload_without_hash(
    integration: ResearchDecisionIntegration,
) -> dict[str, object]:
    payload = asdict(integration)
    payload.pop("integration_hash")
    return payload


def _normalize_requested_identity(
    *,
    requested_theme: str,
    requested_ticker: str,
) -> tuple[str, str]:
    if not isinstance(requested_theme, str):
        raise TypeError("requested_theme must be a string")
    if not isinstance(requested_ticker, str):
        raise TypeError("requested_ticker must be a string")
    theme = requested_theme.strip()
    ticker = requested_ticker.strip().upper()
    if not theme:
        raise ValueError("requested_theme must be non-empty")
    if not ticker:
        raise ValueError("requested_ticker must be non-empty")
    return theme, ticker


def _route_from_tape(
    tape: TapeAssessment,
    inputs: DecisionRoutingInputs,
) -> PlaybookRouting:
    return route_playbooks(
        theme_key=inputs.theme_key,
        tape_state=tape.state,
        tape_stage=tape.stage,
        fundamentals_intact=inputs.fundamentals_intact,
        true_catalyst=inputs.true_catalyst,
        breakout_confirmed=inputs.breakout_confirmed,
        squeeze_confirmed=inputs.squeeze_confirmed,
        stable_regime=inputs.stable_regime,
        overheated_without_upgrade=inputs.overheated_without_upgrade,
        pair_divergence=inputs.pair_divergence,
        structural_repricing=inputs.structural_repricing,
        world_confidence=inputs.world_confidence,
    )


def evaluate_research_decision_integration(
    records: Sequence[ResearchDossierArchiveRecord],
    candidate_archive_record_hash: str,
    *,
    requested_theme: str,
    requested_ticker: str,
    tape: TapeAssessment,
    routing_inputs: DecisionRoutingInputs,
) -> ResearchDecisionIntegration:
    if not isinstance(tape, TapeAssessment):
        raise TypeError("tape must be a TapeAssessment")
    if not isinstance(routing_inputs, DecisionRoutingInputs):
        raise TypeError("routing_inputs must be DecisionRoutingInputs")

    theme, ticker = _normalize_requested_identity(
        requested_theme=requested_theme,
        requested_ticker=requested_ticker,
    )
    readiness = assess_research_decision_readiness(
        records,
        candidate_archive_record_hash,
    )

    work_order = records[0].work_order_archive.work_order
    target_tickers = tuple(
        sorted(target.ticker for target in work_order.targets)
    )

    routing = _route_from_tape(tape, routing_inputs)

    scope_mismatch_reasons: list[str] = []
    if readiness.status is ResearchDecisionReadinessStatus.READY:
        if work_order.research_mode is not ResearchMode.COMPANY_DEEP_DIVE:
            scope_mismatch_reasons.append(
                "company-level research is required"
            )
        if theme != work_order.theme_id:
            scope_mismatch_reasons.append(
                "decision theme does not match research work order"
            )
        if ticker not in target_tickers:
            scope_mismatch_reasons.append(
                "decision ticker is not a frozen research target"
            )

    if readiness.status is ResearchDecisionReadinessStatus.NOT_READY:
        admission = ResearchDecisionAdmissionStatus.RESEARCH_NOT_READY
    elif (
        readiness.status
        is ResearchDecisionReadinessStatus.INDETERMINATE
    ):
        admission = (
            ResearchDecisionAdmissionStatus.RESEARCH_INDETERMINATE
        )
    elif scope_mismatch_reasons:
        admission = (
            ResearchDecisionAdmissionStatus.RESEARCH_SCOPE_MISMATCH
        )
    else:
        admission = ResearchDecisionAdmissionStatus.ADMITTED

    admitted_action = (
        routing.action
        if admission is ResearchDecisionAdmissionStatus.ADMITTED
        else None
    )

    seed = ResearchDecisionIntegration(
        readiness_assessment=readiness,
        research_mode=work_order.research_mode,
        work_order_theme_id=work_order.theme_id,
        work_order_target_tickers=target_tickers,
        requested_theme=theme,
        requested_ticker=ticker,
        admission_status=admission,
        scope_mismatch_reasons=tuple(scope_mismatch_reasons),
        tape=tape,
        tape_hash=canonical_hash(asdict(tape)),
        routing_inputs=routing_inputs,
        routing_inputs_hash=canonical_hash(asdict(routing_inputs)),
        routing=routing,
        routing_hash=canonical_hash(_routing_payload(routing)),
        market_action=routing.action,
        admitted_action=admitted_action,
        limitations=_LIMITATIONS,
        integration_hash="0" * 64,
    )
    return replace(
        seed,
        integration_hash=canonical_hash(
            _integration_payload_without_hash(seed)
        ),
    )
