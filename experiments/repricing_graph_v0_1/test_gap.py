from dataclasses import replace

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

ASOF="2026-09-25T20:00:00+00:00"
AVAILABLE="2026-09-24T20:00:00+00:00"


def ours(kind=EstimateKind.POINT, point=14.0, lower=None, upper=None, calibrated=False):
    if kind is EstimateKind.INTERVAL:
        point=None
        lower = 13.8 if lower is None else lower
        upper = 14.2 if upper is None else upper
    return RealityEstimate(
        variable_id="ETN_FY2026_ADJUSTED_EPS", as_of=ASOF, available_at=AVAILABLE,
        kind=kind, point=point, lower=lower, upper=upper, unit="USD/share",
        period="FY2026", horizon="FY2026", confidence=.6,
        evidence_refs=("e1",), provenance=("primary",), probability_is_calibrated=calibrated,
    )


def market(kind=EstimateKind.POINT, point=13.5, lower=None, upper=None, calibrated=False):
    if kind is EstimateKind.INTERVAL:
        point=None
        lower=13.4 if lower is None else lower
        upper=13.6 if upper is None else upper
    return MarketExpectation(
        variable_id="ETN_FY2026_ADJUSTED_EPS", as_of=ASOF, available_at=AVAILABLE,
        method=MarketExpectationMethod.COMPANY_GUIDANCE, kind=kind, point=point,
        lower=lower, upper=upper, unit="USD/share", period="FY2026", horizon="FY2026",
        confidence=.9, source_refs=("m1",), direct_vs_implied="DIRECT", staleness_days=0,
        probability_is_calibrated=calibrated,
    )


def test_point_gap_is_numerical():
    gap=calculate_expectation_gap(ours(), market())
    assert gap.kind is EstimateKind.POINT
    assert gap.point == pytest.approx(.5)
    assert gap.lower is None and gap.upper is None


def test_interval_minus_point_preserves_interval():
    gap=calculate_expectation_gap(ours(EstimateKind.INTERVAL), market())
    assert gap.kind is EstimateKind.INTERVAL
    assert gap.lower == pytest.approx(.3)
    assert gap.upper == pytest.approx(.7)


def test_interval_minus_interval_uses_safe_bounds():
    gap=calculate_expectation_gap(ours(EstimateKind.INTERVAL), market(EstimateKind.INTERVAL))
    assert gap.lower == pytest.approx(.2)
    assert gap.upper == pytest.approx(.8)


def test_gap_requires_same_variable_unit_period_and_horizon():
    for bad in [
        replace(market(), variable_id="OTHER"),
        replace(market(), unit="EUR/share"),
        replace(market(), period="FY2027"),
        replace(market(), horizon="FY2027"),
    ]:
        with pytest.raises(ValueError, match="comparable"):
            calculate_expectation_gap(ours(), bad)


def test_uncalibrated_input_cannot_yield_calibrated_gap():
    gap=calculate_expectation_gap(ours(calibrated=False), market(calibrated=True))
    assert gap.probability_is_calibrated is False


def test_missing_market_expectation_fails_instead_of_using_momentum():
    with pytest.raises(ValueError, match="market expectation"):
        calculate_expectation_gap(ours(), None)


def test_scenario_summary_requires_explicit_weights_for_expected_return():
    scenarios=(
        ScenarioReturn("BULL", .20, 60, "x", ("e",), None),
        ScenarioReturn("BEAR", -.10, 60, "y", ("e",), None),
    )
    summary=summarize_scenarios(scenarios)
    assert summary.weighted_expected_return is None


def test_scenario_summary_uses_only_explicit_weights_and_normalizes():
    scenarios=(
        ScenarioReturn("BULL", .20, 60, "x", ("e",), .25),
        ScenarioReturn("BASE", .05, 60, "x", ("e",), .50),
        ScenarioReturn("BEAR", -.10, 60, "x", ("e",), .25),
    )
    summary=summarize_scenarios(scenarios)
    assert summary.weighted_expected_return == pytest.approx(.05)
    assert summary.total_weight == pytest.approx(1.0)


def test_scanner_or_playbook_scores_are_not_accepted_as_probabilities():
    bad=ScenarioReturn("BULL", .2, 60, "x", ("e",), .7, probability_is_calibrated=True)
    with pytest.raises(ValueError, match="calibrated"):
        summarize_scenarios((bad,), probability_source="scanner_priority")
