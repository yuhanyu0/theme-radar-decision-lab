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


def _parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return dt


def _nonempty(values: tuple[str, ...], name: str) -> None:
    if not values or any(not str(v).strip() for v in values):
        raise ValueError(f"{name} must be non-empty")


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: NodeType
    label: str

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.label.strip():
            raise ValueError("graph node identifiers and labels must be non-empty")


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    source_node: str
    target_node: str
    edge_type: EdgeType
    direction: str
    magnitude_or_elasticity_range: tuple[float, float] | None
    horizon: str
    confidence: float
    evidence_refs: tuple[str, ...]
    provenance: tuple[str, ...]
    evidence_kinds: tuple[str, ...]
    status: EdgeStatus

    def __post_init__(self) -> None:
        if not self.edge_id.strip():
            raise ValueError("edge_id must be non-empty")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("edge confidence must be in [0,1]")


@dataclass(frozen=True)
class RealityEstimate:
    variable_id: str
    as_of: str
    available_at: str
    kind: EstimateKind
    value: float | None
    low: float | None
    high: float | None
    unit: str
    period: str
    horizon: str
    confidence: float
    evidence_refs: tuple[str, ...]
    probability_is_calibrated: bool

    def __post_init__(self) -> None:
        if _parse_time(self.available_at) > _parse_time(self.as_of):
            raise ValueError("available_at exceeds as_of")
        if self.kind is EstimateKind.POINT:
            if self.value is None or self.low is not None or self.high is not None:
                raise ValueError("point estimate requires value only")
        elif self.kind is EstimateKind.INTERVAL:
            if self.value is not None or self.low is None or self.high is None or self.low > self.high:
                raise ValueError("interval estimate requires ordered low/high")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be in [0,1]")
        _nonempty(self.evidence_refs, "evidence_refs")


@dataclass(frozen=True)
class MarketExpectation:
    variable_id: str
    as_of: str
    available_at: str
    kind: EstimateKind
    value: float | None
    low: float | None
    high: float | None
    unit: str
    period: str
    horizon: str
    confidence: float
    evidence_refs: tuple[str, ...]
    probability_is_calibrated: bool
    method: MarketExpectationMethod
    inference_method: str
    direct_vs_implied: str
    staleness_days: float

    def __post_init__(self) -> None:
        RealityEstimate(
            variable_id=self.variable_id,
            as_of=self.as_of,
            available_at=self.available_at,
            kind=self.kind,
            value=self.value,
            low=self.low,
            high=self.high,
            unit=self.unit,
            period=self.period,
            horizon=self.horizon,
            confidence=self.confidence,
            evidence_refs=self.evidence_refs,
            probability_is_calibrated=self.probability_is_calibrated,
        )
        if self.staleness_days < 0 or not isfinite(self.staleness_days):
            raise ValueError("staleness_days must be finite and non-negative")
        if not self.inference_method.strip():
            raise ValueError("inference_method must be non-empty")


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

    def __post_init__(self) -> None:
        if not self.catalyst_id.strip() or not self.source_ref.strip():
            raise ValueError("catalyst id/source must be non-empty")


@dataclass(frozen=True)
class ScenarioReturn:
    name: str
    weight: float | None
    expected_return: float
    horizon: str
    condition: str
    evidence_refs: tuple[str, ...]
    probability_is_calibrated: bool

    def __post_init__(self) -> None:
        if self.weight is not None and (not isfinite(self.weight) or self.weight < 0):
            raise ValueError("scenario weight must be non-negative")
        if not isfinite(self.expected_return):
            raise ValueError("expected_return must be finite")
        _nonempty(self.evidence_refs, "evidence_refs")


@dataclass(frozen=True)
class KeyUnknown:
    unknown_id: str
    affected_graph_nodes: tuple[str, ...]
    current_range: tuple[float, float] | None
    decision_sensitivity: str
    candidate_research_actions: tuple[str, ...]
    estimated_research_cost: str
    status: str


@dataclass(frozen=True)
class RepricingGraph:
    graph_id: str
    as_of: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


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
    catalyst_refs: tuple[str, ...]
    scenarios: tuple[ScenarioReturn, ...]
    thesis: str
    strongest_counter_thesis: str
    invalidation_conditions: tuple[str, ...]
    key_unknowns: tuple[KeyUnknown, ...]
    status: str
    provenance: tuple[str, ...]


def validate_repricing_graph(graph: RepricingGraph) -> None:
    if not graph.graph_id.strip():
        raise ValueError("graph_id must be non-empty")
    _parse_time(graph.as_of)
    node_ids = [n.node_id for n in graph.nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("duplicate graph node")
    edge_ids = [e.edge_id for e in graph.edges]
    if len(edge_ids) != len(set(edge_ids)):
        raise ValueError("duplicate graph edge")
    known = set(node_ids)
    for edge in graph.edges:
        if edge.source_node not in known or edge.target_node not in known:
            raise ValueError("edge references unknown node")
        if not edge.evidence_refs or not edge.provenance:
            raise ValueError("edge evidence/provenance must be non-empty")
        if edge.edge_type in {EdgeType.EXPOSES, EdgeType.IMPLIES}:
            kinds = {k.upper() for k in edge.evidence_kinds}
            if not kinds or kinds <= {"STATISTICAL_LINKAGE"}:
                raise ValueError("causal exposure/implication requires non-linkage causal evidence")


def validate_repricing_case(case: RepricingCase) -> None:
    if not case.case_id.strip() or not case.theme_id.strip() or not case.ticker.strip():
        raise ValueError("case identifiers must be non-empty")
    _parse_time(case.as_of)
    if case.our_expectation is not None and _parse_time(case.our_expectation.available_at) > _parse_time(case.as_of):
        raise ValueError("our expectation exceeds case as_of")
    if case.market_expectation is not None and _parse_time(case.market_expectation.available_at) > _parse_time(case.as_of):
        raise ValueError("market expectation exceeds case as_of")
