from __future__ import annotations

from pathlib import Path

import pytest

from decision_lab.linkage import LinkageResult
from decision_lab.tape import TapeAssessment
from experiments.repricing_graph_v0_1.case_io import load_shadow_case
from experiments.repricing_graph_v0_1.context import RepricingContext
from experiments.repricing_graph_v0_1.gap import calculate_expectation_gap
from experiments.repricing_graph_v0_1.shadow_case import (
    compile_shadow_repricing_decision,
)
from experiments.repricing_graph_v0_1.template import load_etn_template

CASE_PATH = Path(__file__).with_name("cases") / "ETN_2026Q2_shadow.yaml"
TEMPLATE_PATH = Path(__file__).with_name("datacenter_etn_template.yaml")


def _context(*, causal=True, tape_stage="B3"):
    return RepricingContext(
        theme_market_observation_ref="obs:datacenter",
        target_excluded_linkage=LinkageResult(
            ticker="ETN",
            control_name="theme_control_minus_ETN",
            window=63,
            correlation=0.7,
            beta=0.8,
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
            stage=tape_stage,
            support=400.0,
            reclaim=420.0,
            pivot=430.0,
            invalidation=395.0,
            higher_low=True,
            new_low_recently=False,
            volume_confirmation=True,
            volatility_contraction=True,
            relative_strength_positive=True,
            reasons=("test",),
        ),
        context_as_of="2026-09-25T20:00:00+00:00",
        control_members=("GEV", "POWL", "NVT"),
        causal_exposure_validated=causal,
        warnings=(),
    )


def test_real_guidance_baseline_case_stays_researching_and_not_trade_instruction():
    case = load_shadow_case(CASE_PATH)
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        gap=gap,
        context=_context(),
        graph=load_etn_template(TEMPLATE_PATH),
    )
    assert decision.status == "RESEARCHING"
    assert decision.ticker == "ETN"
    assert decision.expectation_gap == gap
    assert "gap interval crosses zero" in decision.warnings
    assert not hasattr(decision, "position_size")
    assert decision.status not in {"BUY", "SELL", "POSITIONABLE"}


def test_missing_gap_stays_researching_even_with_strong_tape():
    case = load_shadow_case(CASE_PATH)
    decision = compile_shadow_repricing_decision(case=case, gap=None, context=_context())
    assert decision.status == "RESEARCHING"


def test_missing_causal_exposure_stays_researching():
    case = load_shadow_case(CASE_PATH)
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        gap=gap,
        context=_context(causal=False),
    )
    assert decision.status == "RESEARCHING"


def test_dominant_contradiction_invalidates_case():
    case = load_shadow_case(CASE_PATH)
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        gap=gap,
        context=_context(),
        dominant_contradiction=True,
    )
    assert decision.status == "INVALIDATED"


def test_tape_cannot_promote_incomplete_case():
    case = load_shadow_case(CASE_PATH)
    decision = compile_shadow_repricing_decision(
        case=case,
        gap=None,
        context=_context(tape_stage="B3"),
    )
    assert decision.status == "RESEARCHING"


def test_case_hash_is_deterministic_for_identical_frozen_inputs():
    case = load_shadow_case(CASE_PATH)
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    first = compile_shadow_repricing_decision(case=case, gap=gap, context=_context())
    second = compile_shadow_repricing_decision(case=case, gap=gap, context=_context())
    assert first.case_hash == second.case_hash


def test_company_guidance_baseline_cannot_be_promoted_as_model_derived_candidate():
    case = load_shadow_case(CASE_PATH)
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    decision = compile_shadow_repricing_decision(
        case=case,
        gap=gap,
        context=_context(),
        graph=load_etn_template(TEMPLATE_PATH),
    )
    assert decision.status == "RESEARCHING"
    assert "our expectation is not transmission-derived" in decision.warnings


def test_compiler_rejects_case_bound_to_different_graph():
    case = load_shadow_case(CASE_PATH)
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    graph = load_etn_template(TEMPLATE_PATH)
    graph = type(graph)(
        graph_id="different-graph",
        as_of=graph.as_of,
        nodes=graph.nodes,
        edges=graph.edges,
    )
    with pytest.raises(ValueError, match="graph"):
        compile_shadow_repricing_decision(
            case=case,
            gap=gap,
            context=_context(),
            graph=graph,
        )
