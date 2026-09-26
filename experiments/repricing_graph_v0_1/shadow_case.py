from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from decision_lab.ledger import canonical_hash
from decision_lab.tape import TapeAssessment

from .context import RepricingContext
from .gap import ExpectationGap
from .model import (
    EdgeStatus,
    EdgeType,
    EstimateKind,
    KeyUnknown,
    RepricingCase,
    RepricingGraph,
    ScenarioReturn,
    validate_repricing_case,
    validate_repricing_graph,
)


class ShadowDecisionStatus(str, Enum):
    RESEARCHING = "RESEARCHING"
    CANDIDATE = "CANDIDATE"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class ShadowRepricingDecision:
    case_hash: str
    as_of: str
    ticker: str
    theme_id: str
    expectation_gap: ExpectationGap | None
    catalyst_refs: tuple[str, ...]
    tape_context: TapeAssessment
    scenarios: tuple[ScenarioReturn, ...]
    strongest_counter_thesis: str
    invalidation_conditions: tuple[str, ...]
    key_unknowns: tuple[KeyUnknown, ...]
    status: ShadowDecisionStatus
    warnings: tuple[str, ...]


def _gap_strictly_positive(gap: ExpectationGap | None) -> bool:
    if gap is None:
        return False
    if gap.kind is EstimateKind.POINT:
        return gap.point is not None and gap.point > 0
    return gap.low is not None and gap.low > 0


def _supported_causal_exposure(graph: RepricingGraph) -> bool:
    return any(
        edge.edge_type is EdgeType.EXPOSES
        and edge.status is EdgeStatus.SUPPORTED
        for edge in graph.edges
    )


def compile_shadow_repricing_decision(
    *,
    case: RepricingCase,
    graph: RepricingGraph,
    gap: ExpectationGap | None,
    context: RepricingContext,
) -> ShadowRepricingDecision:
    validate_repricing_case(case)
    validate_repricing_graph(graph)
    if graph.theme_id != case.theme_id:
        raise ValueError("graph theme does not match case")
    if context.context_as_of != case.as_of:
        raise ValueError("context as_of does not match case")

    contradicted = any(
        edge.status is EdgeStatus.CONTRADICTED for edge in graph.edges
    )
    supported_exposure = _supported_causal_exposure(graph)
    positive_gap = _gap_strictly_positive(gap)
    has_catalyst = bool(case.catalyst_refs)

    warnings = list(context.warnings)
    if not supported_exposure:
        warnings.append("supported causal exposure is missing")
    if gap is None:
        warnings.append("expectation gap is unavailable")
    elif not positive_gap:
        warnings.append("expectation gap is not strictly positive")
    if not has_catalyst:
        warnings.append("bounded catalyst is missing")

    if contradicted:
        status = ShadowDecisionStatus.INVALIDATED
        warnings.append("graph contains contradicted causal relation")
    elif supported_exposure and positive_gap and has_catalyst:
        status = ShadowDecisionStatus.CANDIDATE
    else:
        status = ShadowDecisionStatus.RESEARCHING

    payload = {
        "case": asdict(case),
        "graph": asdict(graph),
        "gap": None if gap is None else asdict(gap),
        "context": asdict(context),
        "status": status.value,
        "warnings": tuple(warnings),
    }
    case_hash = canonical_hash(payload)

    return ShadowRepricingDecision(
        case_hash=case_hash,
        as_of=case.as_of,
        ticker=case.ticker,
        theme_id=case.theme_id,
        expectation_gap=gap,
        catalyst_refs=case.catalyst_refs,
        tape_context=context.tape_assessment,
        scenarios=case.upside_scenarios + case.downside_scenarios,
        strongest_counter_thesis=case.strongest_counter_thesis,
        invalidation_conditions=case.invalidation_conditions,
        key_unknowns=case.key_unknowns,
        status=status,
        warnings=tuple(warnings),
    )
