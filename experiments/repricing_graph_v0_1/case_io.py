from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from decision_lab.themes import ThemePackage

from .model import (
    CatalystRecord,
    EstimateKind,
    MarketExpectation,
    MarketExpectationMethod,
    RealityEstimate,
    RepricingCase,
    ScenarioReturn,
    validate_repricing_case,
)

_FORBIDDEN_FUTURE_FIELDS={
    "realized_20d_return", "realized_60d_return", "future_return", "forward_return",
    "realized_outcome", "mfe", "mae",
}


def _dt(value:str)->datetime:
    if not value: raise ValueError("available_at must be present")
    return datetime.fromisoformat(value)


def _source_index(payload:dict, as_of:str)->dict[str,dict]:
    out={}
    for row in payload.get("sources",[]):
        sid=str(row.get("source_id","")).strip()
        if not sid or sid in out: raise ValueError("source_id must be unique and non-empty")
        if not str(row.get("url","")).strip(): raise ValueError("source provenance url is required")
        available=str(row.get("available_at","")).strip()
        _dt(available)
        if _dt(available)>_dt(as_of): raise ValueError("source available after case as_of")
        if not str(row.get("event_time","")).strip(): raise ValueError("event_time is required")
        if "revision_lineage" not in row: raise ValueError("revision lineage is required")
        out[sid]=row
    return out


def _estimate(raw:dict, sources:dict, as_of:str)->RealityEstimate:
    ref=str(raw["source_ref"])
    src=sources.get(ref)
    if src is None: raise ValueError("unknown reality source")
    kind=EstimateKind(str(raw["kind"]))
    return RealityEstimate(
        variable_id=str(raw["variable_id"]), as_of=as_of, available_at=str(src["available_at"]),
        kind=kind, point=None if raw.get("point") is None else float(raw["point"]),
        lower=None if raw.get("lower") is None else float(raw["lower"]),
        upper=None if raw.get("upper") is None else float(raw["upper"]),
        unit=str(raw["unit"]), period=str(raw["period"]), horizon=str(raw["horizon"]),
        confidence=float(raw["confidence"]), evidence_refs=(ref,), provenance=(str(src["url"]),),
        probability_is_calibrated=bool(raw.get("probability_is_calibrated",False)),
    )


def _market(raw:dict, sources:dict, as_of:str)->MarketExpectation:
    ref=str(raw["source_ref"]); src=sources.get(ref)
    if src is None: raise ValueError("unknown market expectation source")
    method=MarketExpectationMethod(str(raw["method"])); role=str(src.get("source_role",""))
    expected_role={
        MarketExpectationMethod.SELL_SIDE_CONSENSUS:"SELL_SIDE_CONSENSUS",
        MarketExpectationMethod.COMPANY_GUIDANCE:"COMPANY_GUIDANCE",
        MarketExpectationMethod.PRICE_IMPLIED:"MARKET_DATA",
    }[method]
    if role!=expected_role: raise ValueError("market expectation source role does not match method")
    assumptions=tuple(str(x) for x in raw.get("valuation_assumptions",()))
    if method is MarketExpectationMethod.PRICE_IMPLIED and not assumptions:
        raise ValueError("price-implied expectation requires frozen valuation assumptions")
    kind=EstimateKind(str(raw["kind"]))
    return MarketExpectation(
        variable_id=str(raw["variable_id"]), as_of=as_of, available_at=str(src["available_at"]),
        method=method, kind=kind, point=None if raw.get("point") is None else float(raw["point"]),
        lower=None if raw.get("lower") is None else float(raw["lower"]),
        upper=None if raw.get("upper") is None else float(raw["upper"]), unit=str(raw["unit"]),
        period=str(raw["period"]), horizon=str(raw["horizon"]), confidence=float(raw["confidence"]),
        source_refs=(ref,), direct_vs_implied=str(raw["direct_vs_implied"]),
        staleness_days=float(raw["staleness_days"]), probability_is_calibrated=bool(raw.get("probability_is_calibrated",False)),
        valuation_assumptions=assumptions,
    )


def _scenario(row:dict)->ScenarioReturn:
    return ScenarioReturn(
        name=str(row["name"]), expected_return=float(row["expected_return"]),
        horizon_days=int(row["horizon_days"]), condition=str(row["condition"]),
        evidence_refs=tuple(str(x) for x in row.get("evidence_refs",())),
        weight=None if row.get("weight") is None else float(row["weight"]),
        probability_is_calibrated=bool(row.get("probability_is_calibrated",False)),
    )


def load_shadow_case(path:str|Path)->RepricingCase:
    payload=yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    raw_case=dict(payload.get("case",{}))
    if _FORBIDDEN_FUTURE_FIELDS.intersection(raw_case):
        raise ValueError("future outcome fields are forbidden in frozen case input")
    as_of=str(raw_case["as_of"])
    sources=_source_index(payload,as_of)
    reality=_estimate(payload["our_expectation"],sources,as_of)
    market=_market(payload["market_expectation"],sources,as_of)
    cat_raw=dict(payload["catalyst"])
    ref=str(cat_raw["source_ref"])
    if ref not in sources: raise ValueError("unknown catalyst source")
    known_at=str(cat_raw["known_at"])
    if _dt(known_at)>_dt(as_of): raise ValueError("catalyst hindsight: known_at exceeds case as_of")
    catalyst=CatalystRecord(
        catalyst_id=str(cat_raw["catalyst_id"]), event_type=str(cat_raw["event_type"]),
        expected_date_or_window=str(cat_raw["expected_date_or_window"]), known_at=known_at,
        target_node_ids=tuple(str(x) for x in cat_raw.get("target_node_ids",())),
        expected_information=str(cat_raw["expected_information"]), observability=str(cat_raw["observability"]),
        thesis_relevance=str(cat_raw["thesis_relevance"]), source_ref=ref, status=str(cat_raw["status"]),
    )
    scenarios=payload.get("scenarios",{})
    case=RepricingCase(
        case_id=str(raw_case["case_id"]), theme_id=str(raw_case["theme_id"]), ticker=str(raw_case["ticker"]).upper(),
        as_of=as_of, horizon=str(raw_case["horizon"]), graph_ref=str(raw_case["graph_ref"]),
        reality_model_ref=str(raw_case["reality_model_ref"]), market_belief_model_ref=str(raw_case["market_belief_model_ref"]),
        primary_fundamental_variable=str(raw_case["primary_fundamental_variable"]), our_expectation=reality,
        market_expectation=market, expectation_gap=None, gap_uncertainty=str(raw_case["gap_uncertainty"]),
        catalyst_refs=(catalyst.catalyst_id,), current_tape_ref=None,
        upside_scenarios=tuple(_scenario(x) for x in scenarios.get("upside",())),
        downside_scenarios=tuple(_scenario(x) for x in scenarios.get("downside",())),
        thesis=str(raw_case["thesis"]), strongest_counter_thesis=str(raw_case["strongest_counter_thesis"]),
        invalidation_conditions=tuple(str(x) for x in raw_case.get("invalidation_conditions",())),
        key_unknowns=(), status=str(raw_case["status"]), provenance=tuple(str(x) for x in raw_case.get("provenance",())),
        layer=str(raw_case.get("layer","")), catalysts=(catalyst,),
    )
    validate_point_in_time_case(case)
    return case


def validate_point_in_time_case(case:RepricingCase)->None:
    validate_repricing_case(case)
    for catalyst in case.catalysts:
        if _dt(catalyst.known_at)>_dt(case.as_of): raise ValueError("catalyst hindsight: known_at exceeds case as_of")
        if catalyst.catalyst_id not in case.catalyst_refs: raise ValueError("catalyst record is not referenced by case")


def validate_etn_vertical_slice_case(case:RepricingCase, package:ThemePackage)->None:
    if case.ticker!="ETN": raise ValueError("vertical slice target must be ETN")
    if case.theme_id!="DataCenter_Infra": raise ValueError("vertical slice theme must be DataCenter_Infra")
    if case.layer!="electrical_switchgear": raise ValueError("vertical slice layer must be electrical_switchgear")
    if package.definition.theme_id!=case.theme_id: raise ValueError("Theme package mismatch")
    date=case.as_of[:10]
    if package.definition.effective_from and date<package.definition.effective_from:
        raise ValueError("Theme is not effective at case as_of")
    if package.definition.effective_to and date>=package.definition.effective_to:
        raise ValueError("Theme is not effective at case as_of")
    active={c.ticker.upper():c for c in package.universe.active_candidates(as_of=date)}
    if "ETN" not in active: raise ValueError("ETN membership is not effective at case as_of")
    if active["ETN"].layer!=case.layer: raise ValueError("ETN layer mismatch")
