import inspect

import pytest

from experiments.repricing_graph_v0_1.gap import (
    ExpectationGap,
    ScenarioSummary,
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
    payload = dict(
        variable_id="ETN_FY2026_ADJUSTED_EPS",
        as_of="2026-08-04T21:00:00+00:00",
        available_at="2026-08-04T20:15:00+00:00",
        kind=EstimateKind.POINT,
        unit="USD/share",
        period="FY2026",
        horizon="FY2026",
        point=13.80,
        low=None,
        high=None,
        confidence=0.65,
        evidence_refs=("company:q2",),
        provenance=("ours:transmission",),
        probability_is_calibrated=False,
    )
    payload.update(overrides)
    return RealityEstimate(**payload)


def _market(**overrides):
    payload = dict(
        variable_id="ETN_FY2026_ADJUSTED_EPS",
        as_of="2026-08-04T21:00:00+00:00",
        available_at="2026-08-04T20:20:00+00:00",
        kind=EstimateKind.POINT,
        unit="USD/share",
        period="FY2026",
        horizon="FY2026",
        point=13.50,
        low=None,
        high=None,
        confidence=0.5,
        evidence_refs=("market:guidance",),
        provenance=("method:guidance",),
        method=MarketExpectationMethod.COMPANY_GUIDANCE,
        direct_vs_implied="direct",
        staleness_days=0,
        assumptions=(),
        probability_is_calibrated=False,
    )
    payload.update(overrides)
    return MarketExpectation(**payload)


def _scenario(name, weight, ret, calibrated=False):
    return ScenarioReturn(
        name=name,
        weight=weight,
        expected_return=ret,
        horizon_days=60,
        condition=name,
        evidence_refs=(f"scenario:{name}",),
        probability_is_calibrated=calibrated,
        calibration_ref="calibration:v1" if calibrated else None,
    )


def test_point_gap_is_ours_minus_market():
    gap = calculate_expectation_gap(_ours(point=13.8), _market(point=13.5))
    assert isinstance(gap, ExpectationGap)
    assert gap.kind is EstimateKind.POINT
    assert gap.point == pytest.approx(0.3)
    assert gap.low is None and gap.high is None


def test_interval_minus_point_preserves_interval():
    gap = calculate_expectation_gap(
        _ours(kind=EstimateKind.INTERVAL, point=None, low=13.6, high=14.2),
        _market(point=13.5),
    )
    assert gap.kind is EstimateKind.INTERVAL
    assert gap.low == pytest.approx(0.1)
    assert gap.high == pytest.approx(0.7)


def test_interval_minus_interval_uses_safe_bounds():
    gap = calculate_expectation_gap(
        _ours(kind=EstimateKind.INTERVAL, point=None, low=13.6, high=14.2),
        _market(kind=EstimateKind.INTERVAL, point=None, low=13.3, high=13.7),
    )
    assert gap.low == pytest.approx(-0.1)
    assert gap.high == pytest.approx(0.9)


@pytest.mark.parametrize(
    "field,value",
    [
        ("variable_id", "OTHER"),
        ("unit", "percent"),
        ("period", "FY2027"),
        ("horizon", "FY2027"),
    ],
)
def test_gap_requires_matching_semantics(field, value):
    with pytest.raises(ValueError, match=field):
        calculate_expectation_gap(_ours(), _market(**{field: value}))


def test_uncalibrated_input_cannot_yield_calibrated_gap():
    gap = calculate_expectation_gap(_ours(), _market())
    assert gap.probability_is_calibrated is False


def test_missing_market_expectation_fails_instead_of_substituting_price_signal():
    with pytest.raises(TypeError, match="MarketExpectation"):
        calculate_expectation_gap(_ours(), None)


def test_scenario_summary_uses_explicit_weights():
    summary = summarize_scenarios(
        (
            _scenario("bear", 0.2, -0.2),
            _scenario("base", 0.5, 0.1),
            _scenario("bull", 0.3, 0.3),
        )
    )
    assert isinstance(summary, ScenarioSummary)
    assert summary.total_weight == pytest.approx(1.0)
    assert summary.expected_return == pytest.approx(0.10)
    assert summary.probability_is_calibrated is False


def test_zero_total_weight_does_not_invent_expected_return():
    summary = summarize_scenarios(
        (_scenario("bear", 0.0, -0.2), _scenario("bull", 0.0, 0.3))
    )
    assert summary.total_weight == 0.0
    assert summary.expected_return is None


def test_scenario_summary_does_not_accept_scanner_or_playbook_probability_inputs():
    names = tuple(inspect.signature(summarize_scenarios).parameters)
    assert names == ("scenarios",)
    assert "scanner_priority" not in names
    assert "playbook_score" not in names
