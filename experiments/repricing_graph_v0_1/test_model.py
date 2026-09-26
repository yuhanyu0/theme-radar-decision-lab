from dataclasses import fields

import pytest

from experiments.repricing_graph_v0_1.model import (
    CatalystRecord,
    EdgeStatus,
    EdgeType,
    EstimateKind,
    GraphEdge,
    GraphNode,
    KeyUnknown,
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


def _reality(**overrides):
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
        evidence_refs=("company:q2-2026",),
        provenance=("direct:company-guidance-plus-transmission",),
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
        evidence_refs=("market:expectation-source",),
        provenance=("method:company-guidance",),
        method=MarketExpectationMethod.COMPANY_GUIDANCE,
        direct_vs_implied="direct",
        staleness_days=0,
        assumptions=(),
        probability_is_calibrated=False,
    )
    payload.update(overrides)
    return MarketExpectation(**payload)


def _node(node_id, node_type):
    return GraphNode(
        node_id=node_id,
        node_type=node_type,
        label=node_id,
        as_of="2026-08-04T21:00:00+00:00",
        evidence_refs=("evidence:1",),
        provenance=("primary",),
    )


def _edge(**overrides):
    payload = dict(
        edge_id="edge:1",
        source_node="world",
        target_node="exposure",
        edge_type=EdgeType.EXPOSES,
        direction="positive",
        magnitude_low=None,
        magnitude_high=None,
        horizon="12m",
        confidence=0.6,
        evidence_refs=("company:segment-disclosure",),
        provenance=("primary:company",),
        status=EdgeStatus.SUPPORTED,
    )
    payload.update(overrides)
    return GraphEdge(**payload)


def test_enum_contracts_are_frozen():
    assert tuple(item.value for item in NodeType) == (
        "WORLD_STATE",
        "THEME_LAYER_STATE",
        "COMPANY_EXPOSURE",
        "COMPANY_KPI",
        "MARKET_EXPECTATION",
        "CATALYST",
        "PRICE_STATE",
    )
    assert tuple(item.value for item in EdgeType) == (
        "CAUSES",
        "EXPOSES",
        "IMPLIES",
        "REVEALS",
        "PRICES",
    )
    assert tuple(item.value for item in EstimateKind) == ("POINT", "INTERVAL")
    assert tuple(item.value for item in MarketExpectationMethod) == (
        "SELL_SIDE_CONSENSUS",
        "COMPANY_GUIDANCE",
        "PRICE_IMPLIED",
    )


def test_graph_rejects_edge_with_missing_node():
    graph = RepricingGraph(
        graph_id="g",
        theme_id="DataCenter_Infra",
        as_of="2026-08-04T21:00:00+00:00",
        nodes=(_node("world", NodeType.WORLD_STATE),),
        edges=(_edge(target_node="missing"),),
    )
    with pytest.raises(ValueError, match="missing graph node"):
        validate_repricing_graph(graph)


def test_graph_rejects_edge_without_evidence_or_provenance():
    nodes = (
        _node("world", NodeType.WORLD_STATE),
        _node("exposure", NodeType.COMPANY_EXPOSURE),
    )
    for edge in (
        _edge(evidence_refs=()),
        _edge(provenance=()),
    ):
        with pytest.raises(ValueError):
            validate_repricing_graph(
                RepricingGraph("g", "DataCenter_Infra", "2026-08-04T21:00:00+00:00", nodes, (edge,))
            )


def test_exposes_edge_cannot_be_supported_only_by_statistical_linkage():
    graph = RepricingGraph(
        "g",
        "DataCenter_Infra",
        "2026-08-04T21:00:00+00:00",
        (
            _node("world", NodeType.WORLD_STATE),
            _node("exposure", NodeType.COMPANY_EXPOSURE),
        ),
        (_edge(evidence_refs=("linkage:rolling-63d",), provenance=("statistical:linkage",)),),
    )
    with pytest.raises(ValueError, match="economic exposure"):
        validate_repricing_graph(graph)


def test_estimates_reject_future_availability():
    with pytest.raises(ValueError, match="available_at"):
        _reality(available_at="2026-08-05T00:00:00+00:00")
    with pytest.raises(ValueError, match="available_at"):
        _market(available_at="2026-08-05T00:00:00+00:00")


def test_repricing_case_is_generic_not_etn_hardcoded():
    case = RepricingCase(
        case_id="case:generic",
        theme_id="OtherTheme",
        ticker="XYZ",
        as_of="2026-08-04T21:00:00+00:00",
        horizon="60d",
        graph_ref="graph:1",
        reality_model_ref="reality:1",
        market_belief_model_ref="market:1",
        primary_fundamental_variable="XYZ_EPS",
        our_expectation=_reality(variable_id="XYZ_EPS"),
        market_expectation=_market(variable_id="XYZ_EPS"),
        expectation_gap_ref=None,
        gap_uncertainty=None,
        catalyst_refs=(),
        current_tape_ref=None,
        upside_scenarios=(),
        downside_scenarios=(),
        thesis="generic contract",
        strongest_counter_thesis="could be wrong",
        invalidation_conditions=("evidence contradicts transmission",),
        key_unknowns=(),
        status="DISCOVERY",
        provenance=("test",),
    )
    validate_repricing_case(case)
    assert case.ticker == "XYZ"


def test_scenario_weights_must_be_nonnegative():
    with pytest.raises(ValueError, match="weight"):
        ScenarioReturn(
            name="bear",
            weight=-0.1,
            expected_return=-0.2,
            horizon_days=60,
            condition="demand weakens",
            evidence_refs=("evidence:1",),
            probability_is_calibrated=False,
        )


def test_scenario_cannot_claim_calibrated_probability_without_calibration():
    scenario = ScenarioReturn(
        name="base",
        weight=0.5,
        expected_return=0.1,
        horizon_days=60,
        condition="base case",
        evidence_refs=("evidence:1",),
        probability_is_calibrated=False,
    )
    assert scenario.probability_is_calibrated is False
    assert "probability" not in {field.name for field in fields(scenario)}
    with pytest.raises(ValueError, match="calibrated"):
        ScenarioReturn(
            name="base",
            weight=0.5,
            expected_return=0.1,
            horizon_days=60,
            condition="base case",
            evidence_refs=("evidence:1",),
            probability_is_calibrated=True,
            calibration_ref=None,
        )
