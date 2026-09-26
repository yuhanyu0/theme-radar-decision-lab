from __future__ import annotations

import pytest

from experiments.repricing_graph_v0_1.gap import (
    calculate_expectation_gap,
    summarize_scenarios,
)
from experiments.repricing_graph_v0_1.model import (
    EstimateKind,
    MarketExpectation,
    MarketExpectationMethod,
    RealityEstimate,
    ScenarioReturn,
)


def _ours(**overrides):
    payload = {
        "variable_id": "ETN_FY2026_ADJUSTED_EPS",
        "as_of": "2026-09-25T20:00:00+00:00",
        "available_at": "2026-09-25T19:00:00+00:00",
        "kind": EstimateKind.POINT,
        "value": 13.9,
        "low": None,
        "high": None,
        "unit": "USD/share",
        "period": "FY2026",
        "horizon": "FY2026",
        "confidence": 0.6,
        "evidence_refs": ("ours",),
        "probability_is_calibrated": False,
    }
    payload.update(overrides)
    return RealityEstimate(**payload)


def _market(**overrides):
    payload = {
        "variable_id": "ETN_FY2026_ADJUSTED_EPS",
        "as_of": "2026-09-25T20:00:00+00:00",
        "available_at": "2026-09-25T18:00:00+00:00",
        "kind": EstimateKind.POINT,
        "value": 13.5,
        "low": None,
        "high": None,
        "unit": "USD/share",
        "period": "FY2026",
        "horizon": "FY2026",
        "confidence": 0.8,
        "evidence_refs": ("market",),
        "probability_is_calibrated": False,
        "method": MarketExpectationMethod.COMPANY_GUIDANCE,
        "inference_method": "direct guidance",
        "direct_vs_implied": "direct",
        "staleness_days": 0.0,
    }
    payload.update(overrides)
    return MarketExpectation(**payload)


def test_point_gap_is_ours_minus_market():
    gap = calculate_expectation_gap(_ours(), _market())
    assert gap.kind is EstimateKind.POINT
    assert gap.value == pytest.approx(0.4)
    assert gap.low is None
    assert gap.high is None
    assert gap.probability_is_calibrated is False


def test_gap_requires_same_semantic_coordinate():
    with pytest.raises(ValueError, match="coordinate"):
        calculate_expectation_gap(_ours(unit="USD"), _market())

    with pytest.raises(ValueError, match="coordinate"):
        calculate_expectation_gap(_ours(period="FY2027"), _market())


def test_interval_minus_point_preserves_interval():
    ours = _ours(kind=EstimateKind.INTERVAL, value=None, low=13.6, high=14.2)
    gap = calculate_expectation_gap(ours, _market(value=13.5))
    assert gap.kind is EstimateKind.INTERVAL
    assert gap.low == pytest.approx(0.1)
    assert gap.high == pytest.approx(0.7)


def test_interval_minus_interval_uses_conservative_bounds():
    ours = _ours(kind=EstimateKind.INTERVAL, value=None, low=13.6, high=14.2)
    market = _market(kind=EstimateKind.INTERVAL, value=None, low=13.3, high=13.7)
    gap = calculate_expectation_gap(ours, market)
    assert gap.low == pytest.approx(-0.1)
    assert gap.high == pytest.approx(0.9)


def test_gap_calibration_requires_both_sides_calibrated():
    ours = _ours(probability_is_calibrated=True)
    market = _market(probability_is_calibrated=False)
    assert calculate_expectation_gap(ours, market).probability_is_calibrated is False


def test_missing_market_expectation_is_not_replaced_by_other_scores():
    with pytest.raises(TypeError):
        calculate_expectation_gap(_ours(), None)  # type: ignore[arg-type]


def test_scenario_summary_requires_explicit_weights():
    scenarios = (
        ScenarioReturn("bear", None, -0.15, "20d", "bear", ("x",), False),
        ScenarioReturn("base", None, 0.08, "20d", "base", ("x",), False),
    )
    summary = summarize_scenarios(scenarios)
    assert summary.weighted_expected_return is None


def test_scenario_summary_uses_normalized_explicit_weights_only():
    scenarios = (
        ScenarioReturn("bear", 1.0, -0.10, "20d", "bear", ("x",), False),
        ScenarioReturn("base", 3.0, 0.10, "20d", "base", ("x",), False),
    )
    summary = summarize_scenarios(scenarios)
    assert summary.weighted_expected_return == pytest.approx(0.05)
    assert summary.probability_is_calibrated is False
