from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from decision_lab.themes import load_theme_package
from experiments.repricing_graph_v0_1.model import EdgeType
from experiments.repricing_graph_v0_1.template import (
    load_etn_template,
    validate_etn_membership,
)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).with_name("datacenter_etn_template.yaml")
PACKAGE = ROOT / "config" / "themes" / "datacenter_infra.yaml"


def test_template_has_exact_theme_target_layer_and_required_path():
    graph = load_etn_template(TEMPLATE)
    assert graph.graph_id == "DataCenter_Infra:ETN:electrical_switchgear:v0.1"
    node_ids = {node.node_id for node in graph.nodes}
    assert {
        "hyperscaler_ai_datacenter_capex",
        "datacenter_power_demand",
        "electrical_distribution_demand",
        "ETN_electrical_americas",
        "ETN_FY2026_ADJUSTED_EPS",
        "ETN_next_earnings",
        "ETN_market_expected_FY2026_EPS",
    } <= node_ids

    edges = {(edge.source_node, edge.target_node, edge.edge_type) for edge in graph.edges}
    assert (
        "hyperscaler_ai_datacenter_capex",
        "datacenter_power_demand",
        EdgeType.CAUSES,
    ) in edges
    assert (
        "datacenter_power_demand",
        "electrical_distribution_demand",
        EdgeType.CAUSES,
    ) in edges
    assert (
        "electrical_distribution_demand",
        "ETN_electrical_americas",
        EdgeType.EXPOSES,
    ) in edges
    assert (
        "ETN_electrical_americas",
        "ETN_FY2026_ADJUSTED_EPS",
        EdgeType.IMPLIES,
    ) in edges
    assert (
        "ETN_next_earnings",
        "ETN_FY2026_ADJUSTED_EPS",
        EdgeType.REVEALS,
    ) in edges


def test_template_edges_have_non_linkage_provenance_and_no_guessed_elasticity():
    graph = load_etn_template(TEMPLATE)
    for edge in graph.edges:
        assert edge.evidence_refs
        assert edge.provenance
        assert set(edge.evidence_kinds) != {"STATISTICAL_LINKAGE"}
        assert edge.magnitude_or_elasticity_range is None


def test_template_contains_no_trade_instruction():
    text = TEMPLATE.read_text().upper()
    for forbidden in ("BUY", "SELL", "POSITION_SIZE", "PLAYBOOK"):
        assert forbidden not in text


def test_current_etn_membership_is_valid_for_theme_effective_date():
    package = load_theme_package(PACKAGE)
    validate_etn_membership(package, "2026-09-25")


def test_etn_membership_rejects_future_effective_candidate():
    package = load_theme_package(PACKAGE)
    candidate = package.universe.candidates["ETN"]
    mutated = replace(candidate, effective_from="2026-10-01")
    package.universe.candidates["ETN"] = mutated
    with pytest.raises(ValueError, match="effective"):
        validate_etn_membership(package, "2026-09-25")
