from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from decision_lab.themes import ThemePackage

from .model import (
    CatalystRecord,
    EstimateKind,
    KeyUnknown,
    MarketExpectation,
    MarketExpectationMethod,
    RealityEstimate,
    RepricingCase,
    ScenarioReturn,
    validate_repricing_case,
)


_ALLOWED_TOP_LEVEL = {
    "version",
    "case_id",
    "theme_id",
    "layer",
    "ticker",
    "as_of",
    "horizon",
    "graph_ref",
    "reality_model_ref",
    "market_belief_model_ref",
    "primary_fundamental_variable",
    "expectation_gap_ref",
    "gap_uncertainty",
    "current_tape_ref",
    "thesis",
    "strongest_counter_thesis",
    "invalidation_conditions",
    "key_unknowns",
    "status",
    "provenance",
    "our_expectation",
    "market_expectation",
    "catalysts",
    "catalyst_refs",
    "upside_scenarios",
    "downside_scenarios",
    "sources",
}


_SOURCE_FIELDS = {
    "source_id",
    "url",
    "event_time",
    "available_at",
    "variable_id",
    "value",
    "unit",
    "period",
    "revision_lineage",
    "direct_or_inferred",
    "source_kind",
    "notes",
}


_EXPECTED_SOURCE_KIND = {
    MarketExpectationMethod.SELL_SIDE_CONSENSUS: "sell_side_consensus",
    MarketExpectationMethod.COMPANY_GUIDANCE: "management_guidance",
    MarketExpectationMethod.PRICE_IMPLIED: "price_implied",
}


def _utc(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field} must be a list")
    out = tuple(str(item).strip() for item in value)
    if any(not item for item in out):
        raise ValueError(f"{field} contains blank value")
    return out


def _validate_sources(payload: dict[str, object], *, case_as_of: str) -> dict[str, dict]:
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("case sources must be non-empty")
    case_dt = _utc(case_as_of, field="case as_of")
    indexed: dict[str, dict] = {}
    for source in sources:
        if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
            raise ValueError("invalid source record")
        for field in _SOURCE_FIELDS:
            value = source[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"source {field} must be non-empty")
        if _utc(source["available_at"], field="source available_at") > case_dt:
            raise ValueError("source available_at exceeds case as_of")
        _utc(source["event_time"], field="source event_time")
        source_id = source["source_id"]
        if source_id in indexed:
            raise ValueError("duplicate source_id")
        indexed[source_id] = source
    return indexed


def _reality(row: dict) -> RealityEstimate:
    _utc(row.get("available_at"), field="our expectation available_at")
    return RealityEstimate(
        variable_id=row["variable_id"],
        as_of=row["as_of"],
        available_at=row["available_at"],
        kind=EstimateKind(row["kind"]),
        unit=row["unit"],
        period=row["period"],
        horizon=row["horizon"],
        point=row.get("point"),
        low=row.get("low"),
        high=row.get("high"),
        confidence=float(row["confidence"]),
        evidence_refs=_tuple(row["evidence_refs"], field="our expectation evidence_refs"),
        provenance=_tuple(row["provenance"], field="our expectation provenance"),
        probability_is_calibrated=bool(row.get("probability_is_calibrated", False)),
    )


def _market(row: dict) -> MarketExpectation:
    _utc(row.get("available_at"), field="market expectation available_at")
    return MarketExpectation(
        variable_id=row["variable_id"],
        as_of=row["as_of"],
        available_at=row["available_at"],
        kind=EstimateKind(row["kind"]),
        unit=row["unit"],
        period=row["period"],
        horizon=row["horizon"],
        point=row.get("point"),
        low=row.get("low"),
        high=row.get("high"),
        confidence=float(row["confidence"]),
        evidence_refs=_tuple(row["evidence_refs"], field="market expectation evidence_refs"),
        provenance=_tuple(row["provenance"], field="market expectation provenance"),
        method=MarketExpectationMethod(row["method"]),
        direct_vs_implied=row["direct_vs_implied"],
        staleness_days=int(row["staleness_days"]),
        assumptions=_tuple(row.get("assumptions", []), field="market expectation assumptions"),
        probability_is_calibrated=bool(row.get("probability_is_calibrated", False)),
    )


def _scenario(row: dict) -> ScenarioReturn:
    return ScenarioReturn(
        name=row["name"],
        weight=float(row["weight"]),
        expected_return=float(row["expected_return"]),
        horizon_days=int(row["horizon_days"]),
        condition=row["condition"],
        evidence_refs=_tuple(row["evidence_refs"], field="scenario evidence_refs"),
        probability_is_calibrated=bool(row.get("probability_is_calibrated", False)),
        calibration_ref=row.get("calibration_ref"),
    )


def _unknown(row: dict) -> KeyUnknown:
    return KeyUnknown(
        unknown_id=row["unknown_id"],
        affected_graph_nodes=_tuple(row["affected_graph_nodes"], field="affected_graph_nodes"),
        current_range=row["current_range"],
        decision_sensitivity=row["decision_sensitivity"],
        candidate_research_actions=_tuple(
            row["candidate_research_actions"],
            field="candidate_research_actions",
        ),
        estimated_research_cost=row["estimated_research_cost"],
        status=row["status"],
    )


def validate_point_in_time_case(case: RepricingCase) -> None:
    validate_repricing_case(case)
    case_dt = _utc(case.as_of, field="case as_of")
    for label, estimate in (
        ("our expectation", case.our_expectation),
        ("market expectation", case.market_expectation),
    ):
        if _utc(estimate.as_of, field=f"{label} as_of") > case_dt:
            raise ValueError(f"{label} as_of exceeds case as_of")
        if _utc(estimate.available_at, field=f"{label} available_at") > case_dt:
            raise ValueError(f"{label} available_at exceeds case as_of")


def validate_etn_vertical_slice_case(
    case: RepricingCase,
    package: ThemePackage,
) -> None:
    if case.ticker != "ETN":
        raise ValueError("ETN vertical slice requires ETN target")
    if case.theme_id != "DataCenter_Infra":
        raise ValueError("ETN vertical slice theme mismatch")
    if package.definition.theme_id != "DataCenter_Infra":
        raise ValueError("ETN vertical slice package theme mismatch")

    case_date = _utc(case.as_of, field="case as_of").date().isoformat()
    definition = package.definition
    if definition.effective_from is not None and case_date < definition.effective_from:
        raise ValueError("Theme is not effective at case as_of")
    if definition.effective_to is not None and case_date >= definition.effective_to:
        raise ValueError("Theme is not effective at case as_of")

    target = package.universe.candidates.get("ETN")
    if target is None or not target.is_effective(case_date):
        raise ValueError("ETN is not effective at case as_of")
    if target.layer != "electrical_switchgear":
        raise ValueError("ETN vertical slice layer mismatch")


def load_shadow_case(path: str | Path) -> RepricingCase:
    payload = yaml.safe_load(Path(path).read_text())
    if not isinstance(payload, dict):
        raise TypeError("shadow case must be mapping")

    unknown = set(payload) - _ALLOWED_TOP_LEVEL
    if any(key.startswith("realized_") or "outcome" in key.lower() for key in unknown):
        raise ValueError("future outcome fields are not allowed in frozen case")
    if unknown:
        raise ValueError(f"unsupported shadow case fields: {sorted(unknown)}")

    if payload.get("ticker") != "ETN":
        raise ValueError("ETN vertical slice requires ETN target")
    if payload.get("theme_id") != "DataCenter_Infra":
        raise ValueError("ETN vertical slice theme mismatch")
    if payload.get("layer") != "electrical_switchgear":
        raise ValueError("ETN vertical slice layer mismatch")

    case_as_of = payload["as_of"]
    sources = _validate_sources(payload, case_as_of=case_as_of)

    our_row = dict(payload["our_expectation"])
    our_source_id = our_row.pop("source_id")
    if our_source_id not in sources:
        raise ValueError("our expectation source is missing")
    ours = _reality(our_row)

    market_row = dict(payload["market_expectation"])
    market_source_id = market_row.pop("source_id")
    market_source = sources.get(market_source_id)
    if market_source is None:
        raise ValueError("market expectation source is missing")
    market = _market(market_row)
    expected_kind = _EXPECTED_SOURCE_KIND[market.method]
    if market_source["source_kind"] != expected_kind:
        raise ValueError(
            f"{market.method.value} requires source_kind {expected_kind}"
        )

    case_dt = _utc(case_as_of, field="case as_of")
    catalyst_ids: set[str] = set()
    source_urls = {source["url"] for source in sources.values()}
    for row in payload.get("catalysts", []):
        catalyst = CatalystRecord(
            catalyst_id=row["catalyst_id"],
            event_type=row["event_type"],
            expected_date_or_window=row["expected_date_or_window"],
            available_at=row["available_at"],
            target_node_ids=_tuple(row["target_node_ids"], field="catalyst target_node_ids"),
            expected_information=row["expected_information"],
            observability=row["observability"],
            thesis_relevance=row["thesis_relevance"],
            source_ref=row["source_ref"],
            status=row["status"],
        )
        if _utc(catalyst.available_at, field="catalyst available_at") > case_dt:
            raise ValueError("catalyst available_at exceeds case as_of")
        if catalyst.source_ref not in source_urls:
            raise ValueError("catalyst source is not in case sources")
        if catalyst.catalyst_id in catalyst_ids:
            raise ValueError("duplicate catalyst id")
        catalyst_ids.add(catalyst.catalyst_id)

    catalyst_refs = _tuple(payload.get("catalyst_refs", []), field="catalyst_refs")
    if set(catalyst_refs) != catalyst_ids:
        raise ValueError("catalyst refs do not match frozen catalysts")

    case = RepricingCase(
        case_id=payload["case_id"],
        theme_id=payload["theme_id"],
        ticker=payload["ticker"],
        as_of=case_as_of,
        horizon=payload["horizon"],
        graph_ref=payload["graph_ref"],
        reality_model_ref=payload["reality_model_ref"],
        market_belief_model_ref=payload["market_belief_model_ref"],
        primary_fundamental_variable=payload["primary_fundamental_variable"],
        our_expectation=ours,
        market_expectation=market,
        expectation_gap_ref=payload.get("expectation_gap_ref"),
        gap_uncertainty=payload.get("gap_uncertainty"),
        catalyst_refs=catalyst_refs,
        current_tape_ref=payload.get("current_tape_ref"),
        upside_scenarios=tuple(_scenario(row) for row in payload.get("upside_scenarios", [])),
        downside_scenarios=tuple(
            _scenario(row) for row in payload.get("downside_scenarios", [])
        ),
        thesis=payload["thesis"],
        strongest_counter_thesis=payload["strongest_counter_thesis"],
        invalidation_conditions=_tuple(
            payload["invalidation_conditions"],
            field="invalidation_conditions",
        ),
        key_unknowns=tuple(_unknown(row) for row in payload.get("key_unknowns", [])),
        status=payload["status"],
        provenance=_tuple(payload["provenance"], field="provenance"),
    )
    validate_point_in_time_case(case)
    return case
