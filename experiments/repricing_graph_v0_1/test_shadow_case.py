from dataclasses import replace
from pathlib import Path

import pytest

from decision_lab.linkage import LinkageResult
from decision_lab.tape import TapeAssessment

from experiments.repricing_graph_v0_1.case_io import load_shadow_case
from experiments.repricing_graph_v0_1.context import RepricingContext
from experiments.repricing_graph_v0_1.gap import calculate_expectation_gap
from experiments.repricing_graph_v0_1.model import EdgeStatus, EdgeType, EstimateKind
from experiments.repricing_graph_v0_1.shadow_case import (
    ShadowDecisionStatus,
    compile_shadow_repricing_decision,
)
from experiments.repricing_graph_v0_1.template import load_etn_template


CASE = Path("experiments/repricing_graph_v0_1/cases/ETN_2026Q2_shadow.yaml")
TEMPLATE = Path("experiments/repricing_graph_v0_1/datacenter_etn_template.yaml")


def _context(stage="B3"):
    return RepricingContext(
        theme_market_observation_ref="market-observation:shadow",
        target_excluded_linkage=LinkageResult(
            ticker="ETN",
            control_name="control_minus_ETN",
            window=63,
            correlation=0.7,
            beta=1.0,
            r2=0.49,
            residual_mean=0.0,
            residual_vol=0.01,
            beta_stability=0.8,
            decoupling_score=0.2,
            circularity_warning=False,
            observations=63,
        ),
        tape_assessment=TapeAssessment(
            state="clean_retest",
            stage=stage,
            support=400.0,
            reclaim=420.0,
            pivot=430.0,
            invalidation=395.0,
            higher_low=True,
            new_low_recently=False,
            volume_confirmation=True,
            volatility_contraction=True,
            relative_strength_positive=True,
            reasons=("test context",),
        ),
        context_as_of="2026-09-26T03:53:00+00:00",
        target_excluded_members=("NVT", "POWL"),
        warnings=(),
    )


def _fully_supported_graph():
    graph = load_etn_template(TEMPLATE)
    causal = {EdgeType.CAUSES, EdgeType.EXPOSES, EdgeType.IMPLIES}
    return replace(
        graph,
        edges=tuple(
            replace(edge, status=EdgeStatus.SUPPORTED)
            if edge.edge_type in causal
            else edge
            for edge in graph.edges
        ),
    )


def _positive_case():
    case = load_shadow_case(CASE)
    ours = replace(
        case.our_expectation,
        kind=EstimateKind.INTERVAL,
        point=None,
        low=13.9,
        high=14.2,
    )
    return replace(case, our_expectation=ours)


def test_real_case_stays_researching_when_gap_crosses_zero():
    case = load_shadow_case(CASE)
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        graph=load_etn_template(TEMPLATE),
        gap=gap,
        context=_context(),
    )
    assert decision.status is ShadowDecisionStatus.RESEARCHING
    assert decision.expectation_gap.low < 0 < decision.expectation_gap.high


def test_no_gap_is_researching_even_with_strong_tape():
    case = _positive_case()
    decision = compile_shadow_repricing_decision(
        case=case,
        graph=load_etn_template(TEMPLATE),
        gap=None,
        context=_context(stage="B3"),
    )
    assert decision.status is ShadowDecisionStatus.RESEARCHING


def test_missing_supported_causal_exposure_is_researching():
    case = _positive_case()
    graph = load_etn_template(TEMPLATE)
    graph = replace(
        graph,
        edges=tuple(edge for edge in graph.edges if edge.edge_type.value != "EXPOSES"),
    )
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        graph=graph,
        gap=gap,
        context=_context(),
    )
    assert decision.status is ShadowDecisionStatus.RESEARCHING


def test_dominant_contradiction_invalidates_case():
    case = _positive_case()
    graph = load_etn_template(TEMPLATE)
    target = next(edge for edge in graph.edges if edge.edge_id == "electrical_to_etn")
    graph = replace(
        graph,
        edges=tuple(
            replace(edge, status=EdgeStatus.CONTRADICTED) if edge is target else edge
            for edge in graph.edges
        ),
    )
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        graph=graph,
        gap=gap,
        context=_context(),
    )
    assert decision.status is ShadowDecisionStatus.INVALIDATED


def test_positive_gap_does_not_promote_hypothesized_causal_path():
    case = _positive_case()
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        graph=load_etn_template(TEMPLATE),
        gap=gap,
        context=_context(),
    )
    assert gap.low > 0
    assert decision.status is ShadowDecisionStatus.RESEARCHING


def test_positive_auditable_gap_plus_supported_causal_path_becomes_candidate():
    case = _positive_case()
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        graph=_fully_supported_graph(),
        gap=gap,
        context=_context(),
    )
    assert gap.low > 0
    assert case.catalyst_refs
    assert decision.status is ShadowDecisionStatus.CANDIDATE


def test_gap_variable_must_match_primary_fundamental_variable():
    case = _positive_case()
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    wrong = replace(gap, variable_id="OTHER_VARIABLE")
    with pytest.raises(ValueError, match="gap variable"):
        compile_shadow_repricing_decision(
            case=case,
            graph=_fully_supported_graph(),
            gap=wrong,
            context=_context(),
        )


def test_missing_catalyst_stays_researching():
    case = replace(_positive_case(), catalyst_refs=())
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        graph=load_etn_template(TEMPLATE),
        gap=gap,
        context=_context(),
    )
    assert decision.status is ShadowDecisionStatus.RESEARCHING


def test_tape_cannot_promote_incomplete_case():
    case = load_shadow_case(CASE)
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        graph=load_etn_template(TEMPLATE),
        gap=gap,
        context=_context(stage="B3"),
    )
    assert decision.tape_context.stage == "B3"
    assert decision.status is ShadowDecisionStatus.RESEARCHING


def test_identical_frozen_inputs_have_identical_case_hash():
    case = _positive_case()
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    kwargs = dict(
        case=case,
        graph=load_etn_template(TEMPLATE),
        gap=gap,
        context=_context(),
    )
    first = compile_shadow_repricing_decision(**kwargs)
    second = compile_shadow_repricing_decision(**kwargs)
    assert first == second
    assert first.case_hash == second.case_hash


def test_shadow_decision_has_no_live_action_or_position_size():
    case = _positive_case()
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        graph=load_etn_template(TEMPLATE),
        gap=gap,
        context=_context(),
    )
    assert not hasattr(decision, "action")
    assert not hasattr(decision, "position_size")
