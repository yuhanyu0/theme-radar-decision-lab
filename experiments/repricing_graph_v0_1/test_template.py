from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from experiments.repricing_graph_v0_1.model import EdgeType, NodeType, validate_repricing_graph
from experiments.repricing_graph_v0_1.template import load_etn_template

TEMPLATE=Path(__file__).with_name("datacenter_etn_template.yaml")


def test_etn_template_identity_and_layer_are_frozen():
    graph=load_etn_template(TEMPLATE)
    assert graph.theme_id=="DataCenter_Infra"
    assert graph.ticker=="ETN"
    labels={n.node_id:n.label for n in graph.nodes}
    assert labels["electrical_distribution_demand"]
    assert any(n.node_id=="ETN_electrical_americas" and n.node_type is NodeType.COMPANY_EXPOSURE for n in graph.nodes)


def test_etn_template_contains_required_causal_path_and_catalyst():
    graph=load_etn_template(TEMPLATE)
    pairs={(e.source_node,e.target_node,e.edge_type) for e in graph.edges}
    assert ("hyperscaler_ai_datacenter_capex","datacenter_power_demand",EdgeType.CAUSES) in pairs
    assert ("datacenter_power_demand","electrical_distribution_demand",EdgeType.CAUSES) in pairs
    assert ("electrical_distribution_demand","ETN_electrical_americas",EdgeType.EXPOSES) in pairs
    assert ("ETN_electrical_americas","ETN_FY2026_ADJUSTED_EPS",EdgeType.IMPLIES) in pairs
    assert ("ETN_next_earnings","ETN_FY2026_ADJUSTED_EPS",EdgeType.REVEALS) in pairs
    assert any(e.edge_type is EdgeType.PRICES and e.target_node=="ETN_market_expectation_FY2026_EPS" for e in graph.edges)


def test_every_edge_has_non_linkage_provenance_and_no_guessed_magnitude():
    graph=load_etn_template(TEMPLATE)
    for edge in graph.edges:
        assert edge.evidence_refs
        assert edge.provenance
        assert any(not ref.startswith("linkage:") for ref in edge.evidence_refs)
        assert edge.magnitude_range is None


def test_world_to_eps_paths_cannot_skip_company_exposure_step():
    graph=load_etn_template(TEMPLATE)
    edges_by_source={}
    for e in graph.edges:
        edges_by_source.setdefault(e.source_node,[]).append(e)
    paths=[]
    def walk(node,path):
        if node=="ETN_FY2026_ADJUSTED_EPS":
            paths.append(path); return
        for e in edges_by_source.get(node,[]):
            if e.target_node not in [x.target_node for x in path]: walk(e.target_node,path+[e])
    walk("hyperscaler_ai_datacenter_capex",[])
    assert paths
    node_types={n.node_id:n.node_type for n in graph.nodes}
    for path in paths:
        traversed={e.source_node for e in path}|{path[-1].target_node}
        assert any(node_types[n] is NodeType.COMPANY_EXPOSURE for n in traversed)


def test_template_contains_no_trade_or_playbook_directives():
    text=TEMPLATE.read_text().upper()
    for forbidden in ["BUY","SELL","POSITION_SIZE","PLAYBOOK","B2","B3","A1"]:
        assert forbidden not in text


def test_loader_rejects_unsupported_edge_type(tmp_path):
    payload=yaml.safe_load(TEMPLATE.read_text())
    payload["edges"][0]["edge_type"]="CORRELATES"
    p=tmp_path/"bad.yaml"; p.write_text(yaml.safe_dump(payload))
    with pytest.raises(ValueError): load_etn_template(p)
