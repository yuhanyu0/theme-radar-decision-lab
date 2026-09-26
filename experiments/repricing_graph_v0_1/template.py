from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from decision_lab.themes import ThemePackage

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
            magnitude_or_elasticity_range=(
                None
                if row.get("magnitude_or_elasticity_range") is None
                else tuple(float(x) for x in row["magnitude_or_elasticity_range"])
            ),
            horizon=str(row["horizon"]),
            confidence=float(row["confidence"]),
            evidence_refs=tuple(str(x) for x in row["evidence_refs"]),
            provenance=tuple(str(x) for x in row["provenance"]),
            evidence_kinds=tuple(str(x) for x in row["evidence_kinds"]),
            status=EdgeStatus(str(row["status"])),
        )
        for row in payload["edges"]
    )
    graph = RepricingGraph(
        graph_id=str(payload["graph_id"]),
        as_of=str(payload["as_of"]),
        nodes=nodes,
        edges=edges,
    )
    validate_repricing_graph(graph)
    if payload.get("theme_id") != "DataCenter_Infra":
        raise ValueError("ETN template theme mismatch")
    if payload.get("target") != "ETN":
        raise ValueError("ETN template target mismatch")
    if payload.get("layer") != "electrical_switchgear":
        raise ValueError("ETN template layer mismatch")
    return graph


def validate_etn_membership(package: ThemePackage, as_of: str) -> None:
    if package.definition.theme_id != "DataCenter_Infra":
        raise ValueError("ETN template requires DataCenter_Infra")
    day = date.fromisoformat(as_of)
    if package.definition.effective_from and day < date.fromisoformat(
        package.definition.effective_from
    ):
        raise ValueError("theme is not effective at case date")
    if package.definition.effective_to and day >= date.fromisoformat(
        package.definition.effective_to
    ):
        raise ValueError("theme is not effective at case date")
    candidates = {
        item.ticker.upper(): item
        for item in package.universe.active_candidates(as_of=as_of)
    }
    etn = candidates.get("ETN")
    if etn is None or etn.layer != "electrical_switchgear":
        raise ValueError("ETN membership is not effective in electrical_switchgear")
