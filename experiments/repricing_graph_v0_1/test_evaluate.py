from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from decision_lab.linkage import LinkageResult
from decision_lab.tape import TapeAssessment
from experiments.repricing_graph_v0_1.case_io import load_shadow_case
from experiments.repricing_graph_v0_1.context import RepricingContext
from experiments.repricing_graph_v0_1.evaluate import (
    Ablation,
    central_ablation_kill_signal,
    evaluate_shadow_case,
    run_ablation,
)
from experiments.repricing_graph_v0_1.gap import calculate_expectation_gap
from experiments.repricing_graph_v0_1.shadow_case import (
    compile_shadow_repricing_decision,
)

CASE_PATH = Path(__file__).with_name("cases") / "ETN_2026Q2_shadow.yaml"


def _decision():
    case = load_shadow_case(CASE_PATH)
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    context = RepricingContext(
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
            stage="B3",
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
        context_as_of=case.as_of,
        control_members=("GEV", "POWL", "NVT"),
        causal_exposure_validated=True,
        warnings=(),
    )
    return compile_shadow_repricing_decision(case=case, gap=gap, context=context)


def _series(n=90, start="2026-09-01", slope=0.001):
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.Series(100.0 * np.cumprod(np.full(n, 1.0 + slope)), index=idx)


def test_evaluation_waits_for_enough_future_sessions():
    decision = _decision()
    close = _series(n=10, start="2026-09-25")
    record = evaluate_shadow_case(
        decision=decision,
        close=close,
        spy_close=close,
        sector_close=close,
        theme_control_close=close,
    )
    assert record.outcomes_by_baseline["ABSOLUTE"]["20d"] is None
    assert record.outcomes_by_baseline["ABSOLUTE"]["60d"] is None


def test_evaluation_reports_20d_60d_and_multiple_baselines_without_mutation():
    decision = _decision()
    before_hash = decision.case_hash
    close = _series(n=90, start="2026-09-25", slope=0.002)
    spy = _series(n=90, start="2026-09-25", slope=0.001)
    sector = _series(n=90, start="2026-09-25", slope=0.0008)
    theme = _series(n=90, start="2026-09-25", slope=0.0015)
    record = evaluate_shadow_case(
        decision=decision,
        close=close,
        spy_close=spy,
        sector_close=sector,
        theme_control_close=theme,
    )
    assert decision.case_hash == before_hash
    assert set(record.outcomes_by_baseline) == {
        "ABSOLUTE",
        "SPY",
        "SECTOR",
        "THEME_CONTROL",
    }
    assert record.outcomes_by_baseline["ABSOLUTE"]["20d"]["mfe"] is not None
    assert record.outcomes_by_baseline["ABSOLUTE"]["20d"]["mae"] is not None
    assert record.outcomes_by_baseline["SPY"]["20d"]["benchmark_return"] is not None
    assert not hasattr(record, "p_value")
    assert not hasattr(record, "alpha_estimate")


def test_ablation_records_preserve_exact_case_provenance():
    decision = _decision()
    rows = [run_ablation(decision, item) for item in Ablation]
    assert {row.source_case_hash for row in rows} == {decision.case_hash}
    assert {row.ablation for row in rows} == set(Ablation)


def test_no_gap_ablation_cannot_claim_expectation_gap_mechanism():
    decision = _decision()
    row = run_ablation(decision, Ablation.NO_MARKET_EXPECTATION_GAP)
    assert row.expectation_gap_present is False
    assert row.can_claim_expectation_gap_mechanism is False


def test_identical_full_and_no_gap_performance_triggers_kill_signal():
    assert central_ablation_kill_signal(full_metric=0.08, no_gap_metric=0.08)
    assert not central_ablation_kill_signal(full_metric=0.08, no_gap_metric=0.02)
