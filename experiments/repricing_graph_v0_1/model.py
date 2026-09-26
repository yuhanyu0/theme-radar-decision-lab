from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


def _required_refs(name: str, values: tuple[str, ...]) -> None:
    if not values or any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{name} must contain non-empty references")


def _confidence(value: float) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be within [0, 1]")


def _estimate_shape(
    *,
    kind: EstimateKind,
    point: float | None,
    low: float | None,
    high: float | None,
) -> None:
    if not isinstance(kind, EstimateKind):
        raise TypeError("unsupported estimate kind")
    if kind is EstimateKind.POINT:
        if point is None or low is not None or high is not None:
            raise ValueError("POINT estimate requires point only")
        if not isfinite(point):
            raise ValueError("point estimate must be finite")
    else:
        if point is not None or low is None or high is None:
            raise ValueError("INTERVAL estimate requires low/high only")
        if not isfinite(low) or not isfinite(high) or low > high:
            raise ValueError("invalid interval estimate")


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: NodeType
    label: str
    as_of: str
    evidence_refs: tuple[str, ...]
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        _required_text("node_id", self.node_id)
        _required_text("label", self.label)
        if not isinstance(self.node_type, NodeType):
            raise TypeError("unsupported node type")
        _utc(self.as_of)
        _required_refs("evidence_refs", self.evidence_refs)
        _required_refs("provenance", self.provenance)


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    source_node: str
    target_node: str
    edge_type: EdgeType
    direction: str
    magnitude_low: float | None
    magnitude_high: float | None
    horizon: str
    confidence: float
    evidence_refs: tuple[str, ...]
    provenance: tuple[str, ...]
    status: EdgeStatus

    def __post_init__(self) -> None:
        for name, value in (
            ("edge_id", self.edge_id),
            ("source_node", self.source_node),
            ("target_node", self.target_node),
            ("direction", self.direction),
            ("horizon", self.horizon),
        ):
            _required_text(name, value)
        if not isinstance(self.edge_type, EdgeType):
            raise TypeError("unsupported edge type")
        if not isinstance(self.status, EdgeStatus):
            raise TypeError("unsupported edge status")
        if self.magnitude_low is not None and not isfinite(self.magnitude_low):
            raise ValueError("edge magnitude must be finite")
        if self.magnitude_high is not None and not isfinite(self.magnitude_high):
            raise ValueError("edge magnitude must be finite")
        if (
            self.magnitude_low is not None
            and self.magnitude_high is not None
            and self.magnitude_low > self.magnitude_high
        ):
            raise ValueError("invalid edge magnitude range")
        _confidence(self.confidence)
        _required_refs("evidence_refs", self.evidence_refs)
        _required_refs("provenance", self.provenance)


@dataclass(frozen=True)
class RealityEstimate:
    variable_id: str
    as_of: str
    available_at: str
    kind: EstimateKind
    unit: str
    period: str
    horizon: str
    point: float | None
    low: float | None
    high: float | None
    confidence: float
    evidence_refs: tuple[str, ...]
    provenance: tuple[str, ...]
    probability_is_calibrated: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("variable_id", self.variable_id),
            ("unit", self.unit),
            ("period", self.period),
            ("horizon", self.horizon),
        ):
            _required_text(name, value)
        if _utc(self.available_at) > _utc(self.as_of):
            raise ValueError("available_at exceeds as_of")
        _estimate_shape(kind=self.kind, point=self.point, low=self.low, high=self.high)
        _confidence(self.confidence)
        _required_refs("evidence_refs", self.evidence_refs)
        _required_refs("provenance", self.provenance)
        if not isinstance(self.probability_is_calibrated, bool):
            raise TypeError("probability_is_calibrated must be bool")


@dataclass(frozen=True)
class MarketExpectation:
    variable_id: str
    as_of: str
    available_at: str
    kind: EstimateKind
    unit: str
    period: str
    horizon: str
    point: float | None
    low: float | None
    high: float | None
    confidence: float
    evidence_refs: tuple[str, ...]
    provenance: tuple[str, ...]
    method: MarketExpectationMethod
    direct_vs_implied: str
    staleness_days: int
    assumptions: tuple[str, ...]
    probability_is_calibrated: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("variable_id", self.variable_id),
            ("unit", self.unit),
            ("period", self.period),
            ("horizon", self.horizon),
            ("direct_vs_implied", self.direct_vs_implied),
        ):
            _required_text(name, value)
        if not isinstance(self.method, MarketExpectationMethod):
            raise TypeError("unsupported market expectation method")
        if _utc(self.available_at) > _utc(self.as_of):
            raise ValueError("available_at exceeds as_of")
        _estimate_shape(kind=self.kind, point=self.point, low=self.low, high=self.high)
        _confidence(self.confidence)
        if isinstance(self.staleness_days, bool) or not isinstance(self.staleness_days, int):
            raise TypeError("staleness_days must be integer")
        if self.staleness_days < 0:
            raise ValueError("staleness_days must be non-negative")
        _required_refs("evidence_refs", self.evidence_refs)
        _required_refs("provenance", self.provenance)
        if self.method is MarketExpectationMethod.PRICE_IMPLIED and not self.assumptions:
            raise ValueError("price-implied expectation requires assumptions")
        if not isinstance(self.probability_is_calibrated, bool):
            raise TypeError("probability_is_calibrated must be bool")


@dataclass(frozen=True)
class CatalystRecord:
    catalyst_id: str
    event_type: str
    expected_date_or_window: str
    available_at: str
    target_node_ids: tuple[str, ...]
    expected_information: str
    observability: str
    thesis_relevance: str
    source_ref: str
    status: str

    def __post_init__(self) -> None:
        for name, value in (
            ("catalyst_id", self.catalyst_id),
            ("event_type", self.event_type),
            ("expected_date_or_window", self.expected_date_or_window),
            ("expected_information", self.expected_information),
            ("observability", self.observability),
            ("thesis_relevance", self.thesis_relevance),
            ("source_ref", self.source_ref),
            ("status", self.status),
        ):
            _required_text(name, value)
        _utc(self.available_at)
        _required_refs("target_node_ids", self.target_node_ids)


@dataclass(frozen=True)
class ScenarioReturn:
    name: str
    weight: float
    expected_return: float
    horizon_days: int
    condition: str
    evidence_refs: tuple[str, ...]
    probability_is_calibrated: bool = False
    calibration_ref: str | None = None

    def __post_init__(self) -> None:
        _required_text("name", self.name)
        _required_text("condition", self.condition)
        if not isfinite(self.weight) or self.weight < 0:
            raise ValueError("scenario weight must be finite and non-negative")
        if not isfinite(self.expected_return):
            raise ValueError("expected_return must be finite")
        if isinstance(self.horizon_days, bool) or self.horizon_days <= 0:
            raise ValueError("horizon_days must be positive")
        _required_refs("evidence_refs", self.evidence_refs)
        if self.probability_is_calibrated and not self.calibration_ref:
            raise ValueError("calibrated scenario weight requires calibration_ref")
        if self.calibration_ref is not None:
            _required_text("calibration_ref", self.calibration_ref)


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
    our_expectation: RealityEstimate
    market_expectation: MarketExpectation
    expectation_gap_ref: str | None
    gap_uncertainty: float | None
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


_ALLOWED_CASE_STATUS = {
    "DISCOVERY",
    "RESEARCHING",
    "CANDIDATE",
    "POSITIONABLE",
    "INVALIDATED",
    "CLOSED",
}


def validate_repricing_graph(graph: RepricingGraph) -> None:
    _required_text("graph_id", graph.graph_id)
    _required_text("theme_id", graph.theme_id)
    _utc(graph.as_of)
    node_ids = [node.node_id for node in graph.nodes]
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("duplicate graph node")
    edge_ids = [edge.edge_id for edge in graph.edges]
    if len(set(edge_ids)) != len(edge_ids):
        raise ValueError("duplicate graph edge")
    known = set(node_ids)
    for edge in graph.edges:
        if edge.source_node not in known or edge.target_node not in known:
            raise ValueError("edge references missing graph node")
        if (
            edge.edge_type is EdgeType.EXPOSES
            and all(ref.startswith("linkage:") for ref in edge.evidence_refs)
        ):
            raise ValueError("economic exposure requires non-linkage evidence")


def validate_repricing_case(case: RepricingCase) -> None:
    for name, value in (
        ("case_id", case.case_id),
        ("theme_id", case.theme_id),
        ("ticker", case.ticker),
        ("horizon", case.horizon),
        ("graph_ref", case.graph_ref),
        ("reality_model_ref", case.reality_model_ref),
        ("market_belief_model_ref", case.market_belief_model_ref),
        ("primary_fundamental_variable", case.primary_fundamental_variable),
        ("thesis", case.thesis),
        ("strongest_counter_thesis", case.strongest_counter_thesis),
        ("status", case.status),
    ):
        _required_text(name, value)
    _utc(case.as_of)
    if case.status not in _ALLOWED_CASE_STATUS:
        raise ValueError("unsupported repricing case status")
    if case.our_expectation.variable_id != case.primary_fundamental_variable:
        raise ValueError("our expectation variable mismatch")
    if case.market_expectation.variable_id != case.primary_fundamental_variable:
        raise ValueError("market expectation variable mismatch")
    if case.gap_uncertainty is not None and (
        not isfinite(case.gap_uncertainty) or case.gap_uncertainty < 0
    ):
        raise ValueError("gap_uncertainty must be non-negative")
    _required_refs("invalidation_conditions", case.invalidation_conditions)
    _required_refs("provenance", case.provenance)
