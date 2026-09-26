from dataclasses import fields
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from decision_lab.linkage import LinkageResult
from decision_lab.tape import TapeAssessment
from experiments.repricing_graph_v0_1.case_io import load_shadow_case
from experiments.repricing_graph_v0_1.context import RepricingContext
from experiments.repricing_graph_v0_1.evaluate import (
    Ablation,
    AblationRecord,
    ShadowOutcomeRecord,
    evaluate_shadow_case,
    run_ablation,
)
from experiments.repricing_graph_v0_1.gap import calculate_expectation_gap
from experiments.repricing_graph_v0_1.shadow_case import (
    compile_shadow_repricing_decision,
)
from experiments.repricing_graph_v0_1.template import load_etn_template


CASE = Path("experiments/repricing_graph_v0_1/cases/ETN_2026Q2_shadow.yaml")
TEMPLATE = Path("experiments/repricing_graph_v0_1/datacenter_etn_template.yaml")


def _decision():
    case = load_shadow_case(CASE)
    graph = load_etn_template(TEMPLATE)
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    context = RepricingContext(
        theme_market_observation_ref=None,
        target_excluded_linkage=LinkageResult(
            ticker="ETN",
            control_name="control_minus_ETN",
            window=63,
            correlation=0.5,
            beta=1.0,
            r2=0.25,
            residual_mean=0.0,
            residual_vol=0.01,
            beta_stability=0.7,
            decoupling_score=0.3,
            circularity_warning=False,
            observations=63,
        ),
        tape_assessment=TapeAssessment(
            state="transition",
            stage="neutral",
            support=400.0,
            reclaim=420.0,
            pivot=430.0,
            invalidation=395.0,
            higher_low=False,
            new_low_recently=False,
            volume_confirmation=False,
            volatility_contraction=False,
            relative_strength_positive=None,
            reasons=("shadow outcome fixture",),
        ),
        context_as_of=case.as_of,
        target_excluded_members=("NVT", "POWL"),
        warnings=("theme market observation unavailable",),
    )
    return compile_shadow_repricing_decision(
        case=case,
        graph=graph,
        gap=gap,
        context=context,
    )


def _prices(periods=100):
    index = pd.bdate_range("2026-08-10", periods=periods)
    target = pd.Series(np.linspace(400.0, 500.0, periods), index=index)
    spy = pd.Series(np.linspace(650.0, 690.0, periods), index=index)
    sector = pd.Series(np.linspace(150.0, 165.0, periods), index=index)
    theme = pd.Series(np.linspace(200.0, 230.0, periods), index=index)
    return target, spy, sector, theme


def test_outcome_requires_enough_future_sessions_for_20d_and_60d():
    decision = _decision()
    target, spy, sector, theme = _prices(periods=55)
    with pytest.raises(ValueError, match="future sessions"):
        evaluate_shadow_case(
            decision=decision,
            close=target,
            spy_close=spy,
            sector_close=sector,
            theme_control_close=theme,
        )


def test_evaluation_does_not_mutate_frozen_shadow_decision():
    decision = _decision()
    before = decision
    target, spy, sector, theme = _prices()
    record = evaluate_shadow_case(
        decision=decision,
        close=target,
        spy_close=spy,
        sector_close=sector,
        theme_control_close=theme,
    )
    assert isinstance(record, ShadowOutcomeRecord)
    assert decision == before
    assert record.source_case_hash == decision.case_hash


def test_outcomes_report_spy_sector_and_theme_control_relatives():
    target, spy, sector, theme = _prices()
    record = evaluate_shadow_case(
        decision=_decision(),
        close=target,
        spy_close=spy,
        sector_close=sector,
        theme_control_close=theme,
    )
    for horizon in ("20d", "60d"):
        assert record.spy_horizons[horizon]["benchmark_return"] is not None
        assert record.spy_horizons[horizon]["theme_relative_return"] is not None
        assert record.sector_horizons[horizon]["benchmark_return"] is not None
        assert record.theme_control_horizons[horizon]["theme_relative_return"] is not None
        assert record.spy_horizons[horizon]["mfe"] is not None
        assert record.spy_horizons[horizon]["mae"] is not None


def test_all_required_ablations_have_exact_provenance():
    decision = _decision()
    expected = (
        Ablation.FULL,
        Ablation.NO_ECONOMIC_EXPOSURE_VALIDATION,
        Ablation.NO_MARKET_EXPECTATION_GAP,
        Ablation.NO_CATALYST_REQUIREMENT,
        Ablation.NO_TAPE_CONTEXT,
        Ablation.NO_TARGET_EXCLUDED_CONTROL,
    )
    assert tuple(Ablation) == expected
    for ablation in expected:
        record = run_ablation(decision, ablation)
        assert isinstance(record, AblationRecord)
        assert record.ablation is ablation
        assert record.source_case_hash == decision.case_hash
        assert record.provenance == (
            f"source_case:{decision.case_hash}",
            f"ablation:{ablation.value}",
        )


def test_no_market_expectation_gap_cannot_claim_expectation_gap_mechanism():
    record = run_ablation(_decision(), Ablation.NO_MARKET_EXPECTATION_GAP)
    assert record.mechanism_claim_allowed is False
    assert record.kill_if_no_degradation is True


def test_full_mechanism_retains_claim_label_without_claiming_alpha():
    record = run_ablation(_decision(), Ablation.FULL)
    assert record.mechanism_claim_allowed is True
    names = {field.name for field in fields(record)}
    assert "p_value" not in names
    assert "alpha_proven" not in names


def test_ablation_record_does_not_auto_repair_removed_component():
    record = run_ablation(_decision(), Ablation.NO_MARKET_EXPECTATION_GAP)
    assert "replacement_component" not in {field.name for field in fields(record)}
    assert record.removed_component == "market_expectation_gap"
