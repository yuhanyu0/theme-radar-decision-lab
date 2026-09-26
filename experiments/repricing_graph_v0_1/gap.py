from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

from .model import EstimateKind, MarketExpectation, RealityEstimate, ScenarioReturn


@dataclass(frozen=True)
class ExpectationGap:
    variable_id: str
    kind: EstimateKind
    point: float | None
    lower: float | None
    upper: float | None
    unit: str
    period: str
    horizon: str
    probability_is_calibrated: bool


@dataclass(frozen=True)
class ScenarioSummary:
    weighted_expected_return: float | None
    total_weight: float | None
    min_return: float
    max_return: float
    horizon_days: int
    probability_is_calibrated: bool


def _bounds(x: RealityEstimate | MarketExpectation) -> tuple[float, float]:
    if x.kind is EstimateKind.POINT:
        assert x.point is not None
        return float(x.point), float(x.point)
    assert x.lower is not None and x.upper is not None
    return float(x.lower), float(x.upper)


def calculate_expectation_gap(
    ours: RealityEstimate,
    market: MarketExpectation | None,
) -> ExpectationGap:
    if market is None:
        raise ValueError("market expectation is required")
    comparable = (
        ours.variable_id == market.variable_id
        and ours.unit == market.unit
        and ours.period == market.period
        and ours.horizon == market.horizon
    )
    if not comparable:
        raise ValueError("expectations must be comparable on variable/unit/period/horizon")
    ol, ou = _bounds(ours)
    ml, mu = _bounds(market)
    calibrated = bool(ours.probability_is_calibrated and market.probability_is_calibrated)
    if ours.kind is EstimateKind.POINT and market.kind is EstimateKind.POINT:
        return ExpectationGap(
            variable_id=ours.variable_id,
            kind=EstimateKind.POINT,
            point=ol - ml,
            lower=None,
            upper=None,
            unit=ours.unit,
            period=ours.period,
            horizon=ours.horizon,
            probability_is_calibrated=calibrated,
        )
    return ExpectationGap(
        variable_id=ours.variable_id,
        kind=EstimateKind.INTERVAL,
        point=None,
        lower=ol - mu,
        upper=ou - ml,
        unit=ours.unit,
        period=ours.period,
        horizon=ours.horizon,
        probability_is_calibrated=calibrated,
    )


def summarize_scenarios(
    scenarios: tuple[ScenarioReturn, ...],
    *,
    probability_source: str | None = None,
) -> ScenarioSummary:
    if not scenarios:
        raise ValueError("at least one scenario is required")
    horizons = {s.horizon_days for s in scenarios}
    if len(horizons) != 1:
        raise ValueError("scenarios must share one horizon")
    for s in scenarios:
        if s.weight is not None and s.weight < 0:
            raise ValueError("scenario weight must be non-negative")
        if s.probability_is_calibrated and probability_source != "calibrated_model":
            raise ValueError("calibrated probabilities require an explicit calibrated model source")
    weighted = None
    total = None
    if all(s.weight is not None for s in scenarios):
        total = sum(float(s.weight) for s in scenarios if s.weight is not None)
        if total <= 0:
            raise ValueError("scenario weights must sum positive")
        weighted = sum(float(s.expected_return) * float(s.weight) for s in scenarios if s.weight is not None) / total
    return ScenarioSummary(
        weighted_expected_return=weighted,
        total_weight=total,
        min_return=min(float(s.expected_return) for s in scenarios),
        max_return=max(float(s.expected_return) for s in scenarios),
        horizon_days=next(iter(horizons)),
        probability_is_calibrated=bool(
            scenarios and all(s.probability_is_calibrated for s in scenarios)
        ),
    )
