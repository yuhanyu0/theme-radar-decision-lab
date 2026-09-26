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
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    nodes = tuple(
        GraphNode(
            node_id=str(row["node_id"]),
            node_type=NodeType(str(row["node_type"])),
            label=str(row["label"]),
        )
        for row in payload["nodes"]
    )
    edges = tuple(
        GraphEdge(
            edge_id=str(row["edge_id"]),
            source_node=str(row["source_node"]),
            target_node=str(row["target_node"]),
            edge_type=EdgeType(str(row["edge_type"])),
            direction=str(row["direction"]),
            magnitude_range=None,
            horizon=str(row["horizon"]),
            confidence=float(row["confidence"]),
            evidence_refs=tuple(str(x) for x in row.get("evidence_refs", ())),
            provenance=tuple(str(x) for x in row.get("provenance", ())),
            status=EdgeStatus(str(row["status"])),
        )
        for row in payload["edges"]
    )
    graph = RepricingGraph(
        graph_id=str(payload["graph_id"]),
        theme_id=str(payload["theme_id"]),
        ticker=str(payload["ticker"]).upper(),
        as_of=str(payload["as_of"]),
        nodes=nodes,
        edges=edges,
        provenance=tuple(str(x) for x in payload.get("provenance", ())),
    )
    validate_repricing_graph(graph)
    return graph
