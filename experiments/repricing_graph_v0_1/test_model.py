from __future__ import annotations

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


def _estimate(**overrides):
    payload = {
        "variable_id": "ETN_FY2026_ADJUSTED_EPS",
        "as_of": "2026-09-25T20:00:00+00:00",
        "available_at": "2026-09-25T19:00:00+00:00",
        "kind": EstimateKind.POINT,
        "value": 13.75,
        "low": None,
        "high": None,
        "unit": "USD/share",
        "period": "FY2026",
        "horizon": "FY2026",
        "confidence": 0.7,
        "evidence_refs": ("etn-guidance",),
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
        "value": 13.50,
        "low": None,
        "high": None,
        "unit": "USD/share",
        "period": "FY2026",
        "horizon": "FY2026",
        "confidence": 0.8,
        "evidence_refs": ("market-exp",),
        "probability_is_calibrated": False,
        "method": MarketExpectationMethod.COMPANY_GUIDANCE,
        "inference_method": "direct guidance",
        "direct_vs_implied": "direct",
        "staleness_days": 0.0,
    }
    payload.update(overrides)
    return MarketExpectation(**payload)


def test_frozen_node_and_edge_type_sets():
    assert {item.value for item in NodeType} == {
        "WORLD_STATE",
        "THEME_LAYER_STATE",
        "COMPANY_EXPOSURE",
        "COMPANY_KPI",
        "MARKET_EXPECTATION",
        "CATALYST",
        "PRICE_STATE",
    }
    assert {item.value for item in EdgeType} == {
        "CAUSES",
        "EXPOSES",
        "IMPLIES",
        "REVEALS",
        "PRICES",
    }


def test_graph_rejects_missing_node_reference():
    graph = RepricingGraph(
        graph_id="g",
        as_of="2026-09-25T20:00:00+00:00",
        nodes=(GraphNode("world", NodeType.WORLD_STATE, "power demand"),),
        edges=(
            GraphEdge(
                edge_id="e",
                source_node="world",
                target_node="missing",
                edge_type=EdgeType.CAUSES,
                direction="positive",
                magnitude_or_elasticity_range=None,
                horizon="12m",
                confidence=0.5,
                evidence_refs=("primary-source",),
                provenance=("manual",),
                evidence_kinds=("PRIMARY",),
                status=EdgeStatus.SUPPORTED,
            ),
        ),
    )
    with pytest.raises(ValueError, match="unknown node"):
        validate_repricing_graph(graph)


def test_graph_rejects_edge_without_provenance():
    nodes = (
        GraphNode("world", NodeType.WORLD_STATE, "power demand"),
        GraphNode("exposure", NodeType.COMPANY_EXPOSURE, "ETN exposure"),
    )
    edge = GraphEdge(
        edge_id="e",
        source_node="world",
        target_node="exposure",
        edge_type=EdgeType.EXPOSES,
        direction="positive",
        magnitude_or_elasticity_range=None,
        horizon="12m",
        confidence=0.5,
        evidence_refs=(),
        provenance=(),
        evidence_kinds=(),
        status=EdgeStatus.SUPPORTED,
    )
    with pytest.raises(ValueError, match="evidence"):
        validate_repricing_graph(RepricingGraph("g", "2026-09-25T20:00:00+00:00", nodes, (edge,)))


def test_exposes_edge_rejects_statistical_linkage_as_only_support():
    nodes = (
        GraphNode("layer", NodeType.THEME_LAYER_STATE, "electrical demand"),
        GraphNode("exposure", NodeType.COMPANY_EXPOSURE, "ETN exposure"),
    )
    edge = GraphEdge(
        edge_id="e",
        source_node="layer",
        target_node="exposure",
        edge_type=EdgeType.EXPOSES,
        direction="positive",
        magnitude_or_elasticity_range=None,
        horizon="12m",
        confidence=0.5,
        evidence_refs=("rolling-linkage",),
        provenance=("decision_lab.linkage",),
        evidence_kinds=("STATISTICAL_LINKAGE",),
        status=EdgeStatus.SUPPORTED,
    )
    with pytest.raises(ValueError, match="causal"):
        validate_repricing_graph(RepricingGraph("g", "2026-09-25T20:00:00+00:00", nodes, (edge,)))


def test_estimate_rejects_future_availability():
    with pytest.raises(ValueError, match="available_at"):
        _estimate(available_at="2026-09-26T00:00:00+00:00")


def test_market_expectation_method_enum_is_frozen():
    assert {item.value for item in MarketExpectationMethod} == {
        "SELL_SIDE_CONSENSUS",
        "COMPANY_GUIDANCE",
        "PRICE_IMPLIED",
    }
    _market()


def test_generic_case_validation_is_not_etn_specific():
    case = RepricingCase(
        case_id="x",
        theme_id="AnyTheme",
        ticker="ABC",
        as_of="2026-09-25T20:00:00+00:00",
        horizon="20d",
        graph_ref="graph",
        reality_model_ref="reality",
        market_belief_model_ref="market",
        primary_fundamental_variable="EPS",
        our_expectation=None,
        market_expectation=None,
        catalyst_refs=(),
        scenarios=(),
        thesis="",
        strongest_counter_thesis="",
        invalidation_conditions=(),
        key_unknowns=(),
        status="DISCOVERY",
        provenance=("test",),
    )
    validate_repricing_case(case)


def test_scenario_weight_is_nonnegative_and_calibration_is_explicit():
    with pytest.raises(ValueError, match="weight"):
        ScenarioReturn(
            name="bear",
            weight=-0.1,
            expected_return=-0.2,
            horizon="20d",
            condition="demand weakens",
            evidence_refs=("x",),
            probability_is_calibrated=False,
        )

    row = ScenarioReturn(
        name="base",
        weight=0.5,
        expected_return=0.1,
        horizon="20d",
        condition="base case",
        evidence_refs=("x",),
        probability_is_calibrated=False,
    )
    assert row.probability_is_calibrated is False
