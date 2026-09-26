from pathlib import Path

import yaml

from decision_lab.themes import load_theme_package

from experiments.repricing_graph_v0_1.model import EdgeType, NodeType
from experiments.repricing_graph_v0_1.template import load_etn_template


TEMPLATE = Path("experiments/repricing_graph_v0_1/datacenter_etn_template.yaml")
THEME = Path("config/themes/datacenter_infra.yaml")


def test_template_declares_exact_vertical_slice():
    raw = yaml.safe_load(TEMPLATE.read_text())
    assert raw["theme_id"] == "DataCenter_Infra"
    assert raw["target"] == "ETN"
    assert raw["layer"] == "electrical_switchgear"
    assert raw["primary_fundamental_variable"] == "ETN_FY2026_ADJUSTED_EPS"


def test_existing_theme_seed_maps_etn_to_electrical_switchgear():
    package = load_theme_package(THEME)
    target = package.universe.candidates["ETN"]
    assert target.layer == "electrical_switchgear"


def test_template_contains_required_causal_path():
    graph = load_etn_template(TEMPLATE)
    edge_pairs = {(edge.source_node, edge.target_node, edge.edge_type) for edge in graph.edges}
    assert (
        "hyperscaler_ai_datacenter_capex",
        "datacenter_power_demand",
        EdgeType.CAUSES,
    ) in edge_pairs
    assert (
        "datacenter_power_demand",
        "electrical_distribution_demand",
        EdgeType.CAUSES,
    ) in edge_pairs
    assert (
        "electrical_distribution_demand",
        "ETN_electrical_americas",
        EdgeType.EXPOSES,
    ) in edge_pairs
    assert (
        "ETN_electrical_americas",
        "ETN_FY2026_ADJUSTED_EPS",
        EdgeType.IMPLIES,
    ) in edge_pairs
    assert (
        "ETN_next_earnings",
        "ETN_FY2026_ADJUSTED_EPS",
        EdgeType.REVEALS,
    ) in edge_pairs


def test_template_has_market_expectation_node_reached_by_prices_edge():
    graph = load_etn_template(TEMPLATE)
    market_ids = {
        node.node_id
        for node in graph.nodes
        if node.node_type is NodeType.MARKET_EXPECTATION
    }
    assert market_ids
    assert any(
        edge.edge_type is EdgeType.PRICES and edge.target_node in market_ids
        for edge in graph.edges
    )


def test_every_edge_has_non_linkage_provenance():
    graph = load_etn_template(TEMPLATE)
    for edge in graph.edges:
        assert edge.evidence_refs
        assert edge.provenance
        assert any(not ref.startswith("linkage:") for ref in edge.evidence_refs)


def test_template_does_not_guess_edge_elasticities():
    graph = load_etn_template(TEMPLATE)
    for edge in graph.edges:
        assert edge.magnitude_low is None
        assert edge.magnitude_high is None


def test_template_contains_no_trade_or_playbook_instruction():
    text = TEMPLATE.read_text().upper()
    forbidden = ("BUY", "SELL", "POSITION_SIZE", "PLAYBOOK", "BUILD_ON_RETEST", "AGGRESSIVE_PROBE")
    assert not any(term in text for term in forbidden)
