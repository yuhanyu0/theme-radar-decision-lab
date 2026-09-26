from __future__ import annotations

from dataclasses import asdict, dataclass

from decision_lab.ledger import canonical_hash
from decision_lab.tape import TapeAssessment

from .context import RepricingContext
from .gap import ExpectationGap
from .model import (
    KeyUnknown,
    RealityEstimateMethod,
    RepricingCase,
    RepricingGraph,
    ScenarioReturn,
    validate_repricing_graph,
)


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
    status: str
    warnings: tuple[str, ...]


def compile_shadow_repricing_decision(
    *,
    case: RepricingCase,
    gap: ExpectationGap | None,
    context: RepricingContext,
    graph: RepricingGraph | None = None,
    dominant_contradiction: bool = False,
) -> ShadowRepricingDecision:
    warnings = list(context.warnings)

    graph_bound = graph is not None
    if graph is None:
        warnings.append("causal graph not bound")
    else:
        validate_repricing_graph(graph)
        if graph.graph_id != case.graph_ref:
            raise ValueError("case is bound to a different causal graph")
        if graph.as_of > case.as_of:
            raise ValueError("causal graph is future-dated relative to case")

    transmission_derived = bool(
        case.our_expectation is not None
        and case.our_expectation.derivation_method
        is RealityEstimateMethod.CAUSAL_TRANSMISSION
    )
    if not transmission_derived:
        warnings.append("our expectation is not transmission-derived")

    if gap is not None:
        if gap.low is not None and gap.high is not None and gap.low <= 0.0 <= gap.high:
            warnings.append("gap interval crosses zero")
        elif gap.value is not None and gap.value <= 0.0:
            warnings.append("expectation gap is not positive")

    if dominant_contradiction:
        status = "INVALIDATED"
    elif (
        gap is None
        or not context.causal_exposure_validated
        or not case.catalyst_refs
        or not graph_bound
        or not transmission_derived
    ):
        status = "RESEARCHING"
    else:
        status = "CANDIDATE"

    frozen_inputs = {
        "case": asdict(case),
        "gap": None if gap is None else asdict(gap),
        "context": asdict(context),
        "graph": None if graph is None else asdict(graph),
        "dominant_contradiction": bool(dominant_contradiction),
    }
    digest = canonical_hash(frozen_inputs)

    return ShadowRepricingDecision(
        case_hash=digest,
        as_of=case.as_of,
        ticker=case.ticker,
        theme_id=case.theme_id,
        expectation_gap=gap,
        catalyst_refs=case.catalyst_refs,
        tape_context=context.tape_assessment,
        scenarios=case.scenarios,
        strongest_counter_thesis=case.strongest_counter_thesis,
        invalidation_conditions=case.invalidation_conditions,
        key_unknowns=case.key_unknowns,
        status=status,
        warnings=tuple(warnings),
    )
