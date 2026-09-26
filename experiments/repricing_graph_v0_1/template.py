from __future__ import annotations

from pathlib import Path

import yaml

from .model import (
    EdgeStatus,
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    RepricingGraph,
    validate_repricing_graph,
)


def load_etn_template(path: str | Path) -> RepricingGraph:
    payload = yaml.safe_load(Path(path).read_text())
    if payload.get("theme_id") != "DataCenter_Infra":
        raise ValueError("ETN template theme mismatch")
    if payload.get("target") != "ETN":
        raise ValueError("ETN template target mismatch")
    if payload.get("layer") != "electrical_switchgear":
        raise ValueError("ETN template layer mismatch")
    if payload.get("primary_fundamental_variable") != "ETN_FY2026_ADJUSTED_EPS":
        raise ValueError("ETN template KPI mismatch")

    nodes = tuple(
        GraphNode(
            node_id=row["node_id"],
            node_type=NodeType(row["node_type"]),
            label=row["label"],
            as_of=row["as_of"],
            evidence_refs=tuple(row["evidence_refs"]),
            provenance=tuple(row["provenance"]),
        )
        for row in payload["nodes"]
    )
    edges = tuple(
        GraphEdge(
            edge_id=row["edge_id"],
            source_node=row["source_node"],
            target_node=row["target_node"],
            edge_type=EdgeType(row["edge_type"]),
            direction=row["direction"],
            magnitude_low=row.get("magnitude_low"),
            magnitude_high=row.get("magnitude_high"),
            horizon=row["horizon"],
            confidence=float(row["confidence"]),
            evidence_refs=tuple(row["evidence_refs"]),
            provenance=tuple(row["provenance"]),
            status=EdgeStatus(row["status"]),
        )
        for row in payload["edges"]
    )
    graph = RepricingGraph(
        graph_id="DataCenter_Infra:ETN:electrical_switchgear:v0.1",
        theme_id=payload["theme_id"],
        as_of=payload["as_of"],
        nodes=nodes,
        edges=edges,
    )
    validate_repricing_graph(graph)
    return graph
