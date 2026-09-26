from __future__ import annotations

from dataclasses import dataclass

from .model import EstimateKind, MarketExpectation, RealityEstimate, ScenarioReturn


@dataclass(frozen=True)
class ExpectationGap:
    variable_id: str
    kind: EstimateKind
    unit: str
    period: str
    horizon: str
    point: float | None
    low: float | None
    high: float | None
    ours_confidence: float
    market_confidence: float
    probability_is_calibrated: bool


@dataclass(frozen=True)
class ScenarioSummary:
    total_weight: float
    expected_return: float | None
    probability_is_calibrated: bool
    horizon_days: tuple[int, ...]


def _require_same(field: str, ours: RealityEstimate, market: MarketExpectation) -> None:
    if getattr(ours, field) != getattr(market, field):
        raise ValueError(f"{field} mismatch")


def calculate_expectation_gap(
    ours: RealityEstimate,
    market: MarketExpectation,
) -> ExpectationGap:
    if not isinstance(ours, RealityEstimate):
        raise TypeError("ours must be RealityEstimate")
    if not isinstance(market, MarketExpectation):
        raise TypeError("market must be MarketExpectation")

    for field in ("variable_id", "unit", "period", "horizon"):
        _require_same(field, ours, market)

    if ours.kind is EstimateKind.POINT and market.kind is EstimateKind.POINT:
        assert ours.point is not None and market.point is not None
        kind = EstimateKind.POINT
        point = ours.point - market.point
        low = None
        high = None
    else:
        ours_low = ours.point if ours.kind is EstimateKind.POINT else ours.low
        ours_high = ours.point if ours.kind is EstimateKind.POINT else ours.high
        market_low = market.point if market.kind is EstimateKind.POINT else market.low
        market_high = market.point if market.kind is EstimateKind.POINT else market.high
        assert ours_low is not None and ours_high is not None
        assert market_low is not None and market_high is not None
        kind = EstimateKind.INTERVAL
        point = None
        low = ours_low - market_high
        high = ours_high - market_low

    return ExpectationGap(
        variable_id=ours.variable_id,
        kind=kind,
        unit=ours.unit,
        period=ours.period,
        horizon=ours.horizon,
        point=point,
        low=low,
        high=high,
        ours_confidence=ours.confidence,
        market_confidence=market.confidence,
        probability_is_calibrated=(
            ours.probability_is_calibrated and market.probability_is_calibrated
        ),
    )


def summarize_scenarios(
    scenarios: tuple[ScenarioReturn, ...],
) -> ScenarioSummary:
    total_weight = sum(item.weight for item in scenarios)
    expected_return = None
    if total_weight > 0:
        expected_return = (
            sum(item.weight * item.expected_return for item in scenarios)
            / total_weight
        )
    calibrated = bool(scenarios) and all(
        item.probability_is_calibrated for item in scenarios
    )
    return ScenarioSummary(
        total_weight=total_weight,
        expected_return=expected_return,
        probability_is_calibrated=calibrated,
        horizon_days=tuple(sorted({item.horizon_days for item in scenarios})),
    )
