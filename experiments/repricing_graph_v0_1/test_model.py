from dataclasses import replace

import pytest

from experiments.repricing_graph_v0_1.model import (
    EdgeStatus,
    EdgeType,
    EstimateKind,
    GraphEdge,
    GraphNode,
    MarketExpectation,
    MarketExpectationMethod,
    NodeType,
    RealityEstimate,
    RepricingCase,
    RepricingGraph,
    ScenarioReturn,
    validate_repricing_case,
    validate_repricing_graph,
)


def _ts(day="2026-09-25"):
    return f"{day}T20:00:00+00:00"


def _node(node_id, node_type):
    return GraphNode(node_id=node_id, node_type=node_type, label=node_id)


def _edge(**overrides):
    base = dict(
        edge_id="e1",
        source_node="world",
        target_node="layer",
        edge_type=EdgeType.CAUSES,
        direction="POSITIVE",
        magnitude_range=None,
        horizon="12m",
        confidence=0.7,
        evidence_refs=("primary:1",),
        provenance=("company_ir",),
        status=EdgeStatus.SUPPORTED,
    )
    base.update(overrides)
    return GraphEdge(**base)


def _estimate(kind=EstimateKind.POINT, calibrated=False):
    return RealityEstimate(
        variable_id="ETN_FY2026_ADJUSTED_EPS",
        as_of=_ts(),
        available_at=_ts("2026-09-24"),
        kind=kind,
        point=13.8 if kind is EstimateKind.POINT else None,
        lower=13.4 if kind is EstimateKind.INTERVAL else None,
        upper=14.2 if kind is EstimateKind.INTERVAL else None,
        unit="USD/share",
        period="FY2026",
        horizon="FY2026",
        confidence=0.6,
        evidence_refs=("primary:eps",),
        provenance=("company_ir",),
        probability_is_calibrated=calibrated,
    )


def _market():
    return MarketExpectation(
        variable_id="ETN_FY2026_ADJUSTED_EPS",
        as_of=_ts(),
        available_at=_ts("2026-09-24"),
        method=MarketExpectationMethod.COMPANY_GUIDANCE,
        kind=EstimateKind.INTERVAL,
        point=None,
        lower=13.4,
        upper=13.6,
        unit="USD/share",
        period="FY2026",
        horizon="FY2026",
        confidence=0.9,
        source_refs=("company:guidance",),
        direct_vs_implied="DIRECT",
        staleness_days=0.0,
        probability_is_calibrated=False,
    )


def _case():
    return RepricingCase(
        case_id="case-etn",
        theme_id="DataCenter_Infra",
        ticker="ETN",
        as_of=_ts(),
        horizon="60d",
        graph_ref="graph-hash",
        reality_model_ref="reality-hash",
        market_belief_model_ref="market-hash",
        primary_fundamental_variable="ETN_FY2026_ADJUSTED_EPS",
        our_expectation=_estimate(EstimateKind.INTERVAL),
        market_expectation=_market(),
        expectation_gap=None,
        gap_uncertainty="UNCALIBRATED",
        catalyst_refs=("cat-etn",),
        current_tape_ref=None,
        upside_scenarios=(ScenarioReturn("BULL", 0.15, 60, "orders sustain", ("primary:1",), 0.4),),
        downside_scenarios=(ScenarioReturn("BEAR", -0.12, 60, "orders fade", ("primary:2",), 0.3),),
        thesis="Electrical demand translates into EPS above current baseline.",
        strongest_counter_thesis="Demand is already fully reflected in guidance.",
        invalidation_conditions=("orders decelerate",),
        key_unknowns=(),
        status="RESEARCHING",
        provenance=("case:manual",),
    )


def test_frozen_node_edge_enums_are_exact():
    assert {x.value for x in NodeType} == {
        "WORLD_STATE", "THEME_LAYER_STATE", "COMPANY_EXPOSURE", "COMPANY_KPI",
        "MARKET_EXPECTATION", "CATALYST", "PRICE_STATE"
    }
    assert {x.value for x in EdgeType} == {"CAUSES", "EXPOSES", "IMPLIES", "REVEALS", "PRICES"}


def test_graph_rejects_missing_node_ids():
    graph = RepricingGraph(
        graph_id="g",
        theme_id="DataCenter_Infra",
        ticker="ETN",
        as_of=_ts(),
        nodes=(_node("world", NodeType.WORLD_STATE),),
        edges=(_edge(target_node="missing"),),
        provenance=("template:v1",),
    )
    with pytest.raises(ValueError, match="unknown graph node"):
        validate_repricing_graph(graph)


def test_graph_rejects_edge_without_provenance():
    graph = RepricingGraph(
        graph_id="g", theme_id="DataCenter_Infra", ticker="ETN", as_of=_ts(),
        nodes=(_node("world", NodeType.WORLD_STATE), _node("layer", NodeType.THEME_LAYER_STATE)),
        edges=(_edge(evidence_refs=(), provenance=()),), provenance=("template:v1",),
    )
    with pytest.raises(ValueError, match="edge provenance"):
        validate_repricing_graph(graph)


def test_exposes_edge_rejects_statistical_linkage_as_only_support():
    edge = _edge(
        edge_type=EdgeType.EXPOSES,
        evidence_refs=("linkage:rolling63",),
        provenance=("statistical_linkage",),
    )
    graph = RepricingGraph(
        graph_id="g", theme_id="DataCenter_Infra", ticker="ETN", as_of=_ts(),
        nodes=(_node("world", NodeType.WORLD_STATE), _node("layer", NodeType.COMPANY_EXPOSURE)),
        edges=(edge,), provenance=("template:v1",),
    )
    with pytest.raises(ValueError, match="economic evidence"):
        validate_repricing_graph(graph)


def test_estimate_rejects_future_available_at():
    bad = replace(_estimate(), available_at=_ts("2026-09-26"))
    case = replace(_case(), our_expectation=bad)
    with pytest.raises(ValueError, match="available after as_of"):
        validate_repricing_case(case)


def test_generic_case_validation_is_ticker_agnostic():
    other = replace(_case(), ticker="VRT")
    validate_repricing_case(other)


def test_scenario_weight_must_be_nonnegative():
    bad = replace(_case(), upside_scenarios=(ScenarioReturn("BULL", .1, 60, "x", ("e",), -0.1),))
    with pytest.raises(ValueError, match="scenario weight"):
        validate_repricing_case(bad)


def test_calibrated_probability_requires_explicit_calibration_flag():
    bad = replace(_case(), our_expectation=replace(_estimate(), probability_is_calibrated=True, confidence=1.1))
    with pytest.raises(ValueError):
        validate_repricing_case(bad)
