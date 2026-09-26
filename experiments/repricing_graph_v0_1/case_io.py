from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from decision_lab.themes import ThemePackage

from .model import (
    EstimateKind,
    MarketExpectation,
    MarketExpectationMethod,
    RealityEstimate,
    RepricingCase,
    ScenarioReturn,
    validate_repricing_case,
)


def _time(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return dt


def _require_source_rows(payload: dict[str, Any], case_as_of: str) -> dict[str, dict[str, Any]]:
    rows = payload.get("sources")
    if not isinstance(rows, list) or not rows:
        raise ValueError("case requires source provenance")
    as_of = _time(case_as_of)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_id = str(row.get("source_id", "")).strip()
        url = str(row.get("url", "")).strip()
        available_at = row.get("available_at")
        event_time = row.get("event_time")
        if not source_id or not url or not available_at or not event_time:
            raise ValueError("source provenance is incomplete")
        if _time(str(available_at)) > as_of:
            raise ValueError("source available_at exceeds case as_of")
        if _time(str(event_time)) > as_of:
            raise ValueError("source event_time exceeds case as_of")
        if source_id in out:
            raise ValueError("duplicate source_id")
        out[source_id] = dict(row)
    return out


def _estimate(payload: dict[str, Any]) -> RealityEstimate:
    return RealityEstimate(
        variable_id=str(payload["variable_id"]),
        as_of=str(payload["as_of"]),
        available_at=str(payload["available_at"]),
        kind=EstimateKind(str(payload["kind"])),
        value=None if payload.get("value") is None else float(payload["value"]),
        low=None if payload.get("low") is None else float(payload["low"]),
        high=None if payload.get("high") is None else float(payload["high"]),
        unit=str(payload["unit"]),
        period=str(payload["period"]),
        horizon=str(payload["horizon"]),
        confidence=float(payload["confidence"]),
        evidence_refs=tuple(str(x) for x in payload["evidence_refs"]),
        probability_is_calibrated=bool(payload["probability_is_calibrated"]),
    )


def _market(payload: dict[str, Any], sources: dict[str, dict[str, Any]]) -> MarketExpectation:
    available_at = payload.get("available_at")
    if not available_at:
        raise ValueError("market expectation available_at is required")
    method = MarketExpectationMethod(str(payload["method"]))
    source_id = str(payload.get("source_id", ""))
    source = sources.get(source_id)
    if source is None:
        raise ValueError("market expectation source is missing")
    if method is MarketExpectationMethod.SELL_SIDE_CONSENSUS:
        if source.get("source_role") != "sell_side_consensus":
            raise ValueError("sell-side consensus cannot be sourced from management guidance")
    if method is MarketExpectationMethod.PRICE_IMPLIED:
        if not payload.get("valuation_assumptions"):
            raise ValueError("price-implied expectation requires frozen valuation assumptions")
    return MarketExpectation(
        variable_id=str(payload["variable_id"]),
        as_of=str(payload["as_of"]),
        available_at=str(available_at),
        kind=EstimateKind(str(payload["kind"])),
        value=None if payload.get("value") is None else float(payload["value"]),
        low=None if payload.get("low") is None else float(payload["low"]),
        high=None if payload.get("high") is None else float(payload["high"]),
        unit=str(payload["unit"]),
        period=str(payload["period"]),
        horizon=str(payload["horizon"]),
        confidence=float(payload["confidence"]),
        evidence_refs=tuple(str(x) for x in payload["evidence_refs"]),
        probability_is_calibrated=bool(payload["probability_is_calibrated"]),
        method=method,
        inference_method=str(payload["inference_method"]),
        direct_vs_implied=str(payload["direct_vs_implied"]),
        staleness_days=float(payload["staleness_days"]),
    )


def _validate_catalysts(payload: dict[str, Any], sources: dict[str, dict[str, Any]], as_of: str) -> tuple[str, ...]:
    refs: list[str] = []
    cutoff = _time(as_of)
    for row in payload.get("catalysts", []):
        catalyst_id = str(row.get("catalyst_id", "")).strip()
        known_at = row.get("known_at")
        source_ref = str(row.get("source_ref", ""))
        if not catalyst_id or not known_at or source_ref not in sources:
            raise ValueError("catalyst provenance is incomplete")
        if _time(str(known_at)) > cutoff:
            raise ValueError("catalyst was not knowable at case as_of")
        refs.append(catalyst_id)
    return tuple(refs)


def load_shadow_case(path: str | Path) -> RepricingCase:
    payload = yaml.safe_load(Path(path).read_text())
    if "outcomes" in payload:
        raise ValueError("future outcome data cannot be embedded in a frozen case")
    case_data = payload["case"]
    case_as_of = str(case_data["as_of"])
    sources = _require_source_rows(payload, case_as_of)
    ours = _estimate(payload["our_expectation"])
    market = _market(payload["market_expectation"], sources)
    catalyst_refs = _validate_catalysts(payload, sources, case_as_of)
    scenarios = tuple(
        ScenarioReturn(
            name=str(row["name"]),
            weight=None if row.get("weight") is None else float(row["weight"]),
            expected_return=float(row["expected_return"]),
            horizon=str(row["horizon"]),
            condition=str(row["condition"]),
            evidence_refs=tuple(str(x) for x in row["evidence_refs"]),
            probability_is_calibrated=bool(row["probability_is_calibrated"]),
        )
        for row in payload.get("scenarios", [])
    )
    case = RepricingCase(
        case_id=str(case_data["case_id"]),
        theme_id=str(case_data["theme_id"]),
        ticker=str(case_data["ticker"]).upper(),
        as_of=case_as_of,
        horizon=str(case_data["horizon"]),
        graph_ref=str(case_data["graph_ref"]),
        reality_model_ref=str(case_data["reality_model_ref"]),
        market_belief_model_ref=str(case_data["market_belief_model_ref"]),
        primary_fundamental_variable=str(case_data["primary_fundamental_variable"]),
        our_expectation=ours,
        market_expectation=market,
        catalyst_refs=catalyst_refs,
        scenarios=scenarios,
        thesis=str(case_data.get("thesis", "")),
        strongest_counter_thesis=str(case_data.get("strongest_counter_thesis", "")),
        invalidation_conditions=tuple(str(x) for x in case_data.get("invalidation_conditions", [])),
        key_unknowns=(),
        status=str(case_data.get("status", "DISCOVERY")),
        provenance=tuple(sources),
    )
    validate_point_in_time_case(case)
    return case


def validate_point_in_time_case(case: RepricingCase) -> None:
    validate_repricing_case(case)
    if case.our_expectation is None or case.market_expectation is None:
        raise ValueError("shadow case requires both expectation sides")
    cutoff = _time(case.as_of)
    if _time(case.our_expectation.available_at) > cutoff:
        raise ValueError("our expectation exceeds case as_of")
    if _time(case.market_expectation.available_at) > cutoff:
        raise ValueError("market expectation exceeds case as_of")


def validate_etn_vertical_slice_case(case: RepricingCase, package: ThemePackage) -> None:
    if case.ticker != "ETN":
        raise ValueError("vertical slice requires ETN")
    if case.theme_id != "DataCenter_Infra":
        raise ValueError("vertical slice requires DataCenter_Infra")
    if case.primary_fundamental_variable != "ETN_FY2026_ADJUSTED_EPS":
        raise ValueError("vertical slice requires ETN FY2026 adjusted EPS")
    day = date.fromisoformat(_time(case.as_of).date().isoformat())
    definition = package.definition
    if definition.theme_id != "DataCenter_Infra":
        raise ValueError("package theme mismatch")
    if definition.effective_from and day < date.fromisoformat(definition.effective_from):
        raise ValueError("theme is not effective at case date")
    if definition.effective_to and day >= date.fromisoformat(definition.effective_to):
        raise ValueError("theme is not effective at case date")
    active = {item.ticker.upper(): item for item in package.universe.active_candidates(as_of=day.isoformat())}
    etn = active.get("ETN")
    if etn is None or etn.layer != "electrical_switchgear":
        raise ValueError("ETN membership is not effective in electrical_switchgear")
