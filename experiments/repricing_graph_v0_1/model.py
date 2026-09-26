from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


class NodeType(str, Enum):
    WORLD_STATE = "WORLD_STATE"
    THEME_LAYER_STATE = "THEME_LAYER_STATE"
    COMPANY_EXPOSURE = "COMPANY_EXPOSURE"
    COMPANY_KPI = "COMPANY_KPI"
    MARKET_EXPECTATION = "MARKET_EXPECTATION"
    CATALYST = "CATALYST"
    PRICE_STATE = "PRICE_STATE"


class EdgeType(str, Enum):
    CAUSES = "CAUSES"
    EXPOSES = "EXPOSES"
    IMPLIES = "IMPLIES"
    REVEALS = "REVEALS"
    PRICES = "PRICES"


class EdgeStatus(str, Enum):
    HYPOTHESIZED = "HYPOTHESIZED"
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    RETIRED = "RETIRED"


class EstimateKind(str, Enum):
    POINT = "POINT"
    INTERVAL = "INTERVAL"


class MarketExpectationMethod(str, Enum):
    SELL_SIDE_CONSENSUS = "SELL_SIDE_CONSENSUS"
    COMPANY_GUIDANCE = "COMPANY_GUIDANCE"
    PRICE_IMPLIED = "PRICE_IMPLIED"


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: NodeType
    label: str


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    source_node: str
    target_node: str
    edge_type: EdgeType
    direction: str
    magnitude_range: tuple[float, float] | None
    horizon: str
    confidence: float
    evidence_refs: tuple[str, ...]
    provenance: tuple[str, ...]
    status: EdgeStatus


@dataclass(frozen=True)
class RealityEstimate:
    variable_id: str
    as_of: str
    available_at: str
    kind: EstimateKind
    point: float | None
    lower: float | None
    upper: float | None
    unit: str
    period: str
    horizon: str
    confidence: float
    evidence_refs: tuple[str, ...]
    provenance: tuple[str, ...]
    probability_is_calibrated: bool = False


@dataclass(frozen=True)
class MarketExpectation:
    variable_id: str
    as_of: str
    available_at: str
    method: MarketExpectationMethod
    kind: EstimateKind
    point: float | None
    lower: float | None
    upper: float | None
    unit: str
    period: str
    horizon: str
    confidence: float
    source_refs: tuple[str, ...]
    direct_vs_implied: str
    staleness_days: float
    probability_is_calibrated: bool = False
    valuation_assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalystRecord:
    catalyst_id: str
    event_type: str
    expected_date_or_window: str
    known_at: str
    target_node_ids: tuple[str, ...]
    expected_information: str
    observability: str
    thesis_relevance: str
    source_ref: str
    status: str


@dataclass(frozen=True)
class ScenarioReturn:
    name: str
    expected_return: float
    horizon_days: int
    condition: str
    evidence_refs: tuple[str, ...]
    weight: float | None = None
    probability_is_calibrated: bool = False


@dataclass(frozen=True)
class KeyUnknown:
    unknown_id: str
    affected_graph_nodes: tuple[str, ...]
    current_range: str
    decision_sensitivity: str
    candidate_research_actions: tuple[str, ...]
    estimated_research_cost: str
    status: str


@dataclass(frozen=True)
class RepricingGraph:
    graph_id: str
    theme_id: str
    ticker: str
    as_of: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class RepricingCase:
    case_id: str
    theme_id: str
    ticker: str
    as_of: str
    horizon: str
    graph_ref: str
    reality_model_ref: str
    market_belief_model_ref: str
    primary_fundamental_variable: str
    our_expectation: RealityEstimate | None
    market_expectation: MarketExpectation | None
    expectation_gap: object | None
    gap_uncertainty: str
    catalyst_refs: tuple[str, ...]
    current_tape_ref: str | None
    upside_scenarios: tuple[ScenarioReturn, ...]
    downside_scenarios: tuple[ScenarioReturn, ...]
    thesis: str
    strongest_counter_thesis: str
    invalidation_conditions: tuple[str, ...]
    key_unknowns: tuple[KeyUnknown, ...]
    status: str
    provenance: tuple[str, ...]
    layer: str = ""
    catalysts: tuple[CatalystRecord, ...] = ()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_estimate_common(estimate: RealityEstimate | MarketExpectation) -> None:
    if _parse_dt(estimate.available_at) > _parse_dt(estimate.as_of):
        raise ValueError("estimate available after as_of")
    if not estimate.variable_id.strip() or not estimate.unit.strip() or not estimate.period.strip():
        raise ValueError("estimate metadata must be non-empty")
    if not 0.0 <= float(estimate.confidence) <= 1.0:
        raise ValueError("estimate confidence must be in [0,1]")
    if estimate.kind is EstimateKind.POINT:
        if estimate.point is None or not isfinite(float(estimate.point)):
            raise ValueError("point estimate requires finite point")
        if estimate.lower is not None or estimate.upper is not None:
            raise ValueError("point estimate cannot carry interval bounds")
    elif estimate.kind is EstimateKind.INTERVAL:
        if estimate.point is not None or estimate.lower is None or estimate.upper is None:
            raise ValueError("interval estimate requires lower/upper and no point")
        if not isfinite(float(estimate.lower)) or not isfinite(float(estimate.upper)):
            raise ValueError("interval bounds must be finite")
        if float(estimate.lower) > float(estimate.upper):
            raise ValueError("interval lower exceeds upper")
    else:
        raise TypeError("unsupported estimate kind")


def validate_repricing_graph(graph: RepricingGraph) -> None:
    if not graph.graph_id.strip() or not graph.theme_id.strip() or not graph.ticker.strip():
        raise ValueError("graph identity must be non-empty")
    node_ids = [node.node_id for node in graph.nodes]
    if len(set(node_ids)) != len(node_ids) or any(not node_id.strip() for node_id in node_ids):
        raise ValueError("graph node ids must be unique and non-empty")
    known = set(node_ids)
    edge_ids: set[str] = set()
    for edge in graph.edges:
        if edge.edge_id in edge_ids or not edge.edge_id.strip():
            raise ValueError("graph edge ids must be unique and non-empty")
        edge_ids.add(edge.edge_id)
        if edge.source_node not in known or edge.target_node not in known:
            raise ValueError("unknown graph node")
        if not edge.evidence_refs or not edge.provenance:
            raise ValueError("edge provenance is required")
        if not 0.0 <= float(edge.confidence) <= 1.0:
            raise ValueError("edge confidence must be in [0,1]")
        if edge.edge_type in {EdgeType.EXPOSES, EdgeType.IMPLIES}:
            only_linkage = all(
                ref.lower().startswith("linkage:") or "statistical_linkage" in ref.lower()
                for ref in (*edge.evidence_refs, *edge.provenance)
            )
            if only_linkage:
                raise ValueError("economic evidence is required for exposure/implication edges")


def _validate_scenario(scenario: ScenarioReturn) -> None:
    if scenario.horizon_days <= 0:
        raise ValueError("scenario horizon must be positive")
    if not isfinite(float(scenario.expected_return)):
        raise ValueError("scenario return must be finite")
    if scenario.weight is not None and (not isfinite(float(scenario.weight)) or scenario.weight < 0.0):
        raise ValueError("scenario weight must be non-negative")
    if scenario.probability_is_calibrated and scenario.weight is None:
        raise ValueError("calibrated scenario probability requires a weight")
    if not scenario.evidence_refs:
        raise ValueError("scenario evidence is required")


def validate_repricing_case(case: RepricingCase) -> None:
    if not case.case_id.strip() or not case.theme_id.strip() or not case.ticker.strip():
        raise ValueError("case identity must be non-empty")
    if not case.provenance:
        raise ValueError("case provenance is required")
    if case.our_expectation is not None:
        _validate_estimate_common(case.our_expectation)
        if _parse_dt(case.our_expectation.available_at) > _parse_dt(case.as_of):
            raise ValueError("estimate available after as_of")
    if case.market_expectation is not None:
        _validate_estimate_common(case.market_expectation)
        if _parse_dt(case.market_expectation.available_at) > _parse_dt(case.as_of):
            raise ValueError("estimate available after as_of")
        if not case.market_expectation.source_refs:
            raise ValueError("market expectation source is required")
        if case.market_expectation.method is MarketExpectationMethod.PRICE_IMPLIED and not case.market_expectation.valuation_assumptions:
            raise ValueError("price-implied expectation requires valuation assumptions")
    for scenario in (*case.upside_scenarios, *case.downside_scenarios):
        _validate_scenario(scenario)
