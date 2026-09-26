from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from .model import EstimateKind, MarketExpectation, RealityEstimate, ScenarioReturn


@dataclass(frozen=True)
class ExpectationGap:
    variable_id: str
    unit: str
    period: str
    horizon: str
    kind: EstimateKind
    value: float | None
    low: float | None
    high: float | None
    probability_is_calibrated: bool


@dataclass(frozen=True)
class ScenarioSummary:
    weighted_expected_return: float | None
    horizon: str | None
    probability_is_calibrated: bool


def _bounds(estimate: RealityEstimate | MarketExpectation) -> tuple[float, float]:
    if estimate.kind is EstimateKind.POINT:
        assert estimate.value is not None
        return float(estimate.value), float(estimate.value)
    assert estimate.low is not None and estimate.high is not None
    return float(estimate.low), float(estimate.high)


def calculate_expectation_gap(
    ours: RealityEstimate,
    market: MarketExpectation,
) -> ExpectationGap:
    if not isinstance(ours, RealityEstimate) or not isinstance(market, MarketExpectation):
        raise TypeError("expectation gap requires explicit ours and market estimates")

    ours_coord = (ours.variable_id, ours.unit, ours.period, ours.horizon)
    market_coord = (market.variable_id, market.unit, market.period, market.horizon)
    if ours_coord != market_coord:
        raise ValueError("expectation estimates must share the same semantic coordinate")

    ours_low, ours_high = _bounds(ours)
    market_low, market_high = _bounds(market)
    calibrated = bool(
        ours.probability_is_calibrated and market.probability_is_calibrated
    )

    if ours.kind is EstimateKind.POINT and market.kind is EstimateKind.POINT:
        return ExpectationGap(
            variable_id=ours.variable_id,
            unit=ours.unit,
            period=ours.period,
            horizon=ours.horizon,
            kind=EstimateKind.POINT,
            value=ours_low - market_low,
            low=None,
            high=None,
            probability_is_calibrated=calibrated,
        )

    return ExpectationGap(
        variable_id=ours.variable_id,
        unit=ours.unit,
        period=ours.period,
        horizon=ours.horizon,
        kind=EstimateKind.INTERVAL,
        value=None,
        low=ours_low - market_high,
        high=ours_high - market_low,
        probability_is_calibrated=False,
    )


def summarize_scenarios(
    scenarios: tuple[ScenarioReturn, ...],
) -> ScenarioSummary:
    if not scenarios:
        return ScenarioSummary(None, None, False)

    horizons = {item.horizon for item in scenarios}
    if len(horizons) != 1:
        raise ValueError("scenarios must share one horizon")

    if any(item.weight is None for item in scenarios):
        return ScenarioSummary(None, next(iter(horizons)), False)

    weights = [float(item.weight) for item in scenarios if item.weight is not None]
    total = sum(weights)
    if total <= 0.0:
        raise ValueError("scenario weights must sum to a positive value")

    if any(item.probability_is_calibrated for item in scenarios) and (
        not all(item.probability_is_calibrated for item in scenarios)
        or not isclose(total, 1.0)
    ):
        raise ValueError("calibrated scenario probabilities must sum to one")
    expected = sum(
        float(item.weight) * item.expected_return
        for item in scenarios
        if item.weight is not None
    ) / total
    calibrated = all(item.probability_is_calibrated for item in scenarios)
    return ScenarioSummary(expected, next(iter(horizons)), calibrated)
