from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import numpy as np

from decision_lab.ledger import canonical_hash
from decision_lab.tape import TapeAssessment

from .context import RepricingContext
from .gap import ExpectationGap, calculate_expectation_gap
from .model import (
    CatalystRecord,
    EdgeStatus,
    EdgeType,
    KeyUnknown,
    NodeType,
    RealityEstimateMethod,
    RepricingCase,
    RepricingGraph,
    ScenarioReturn,
    _parse_time,
    validate_repricing_case,
    validate_repricing_graph,
)


def json_values(value):
    """Normalize native NumPy scalars at transport only; preserve boolean/numeric meaning."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key: json_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_values(item) for item in value]
    return value


@dataclass(frozen=True)
class ShadowRepricingDecision:
    case_hash: str
    as_of: str
    ticker: str
    theme_id: str
    expectation_gap: ExpectationGap | None
    catalyst_refs: tuple[str, ...]
    tape_context: TapeAssessment
    scenarios: tuple[ScenarioReturn, ...]
    strongest_counter_thesis: str
    invalidation_conditions: tuple[str, ...]
    key_unknowns: tuple[KeyUnknown, ...]
    status: str
    warnings: tuple[str, ...]
    catalysts: tuple[CatalystRecord, ...]
    frozen_inputs_json: str


def _supported_path(case: RepricingCase, graph: RepricingGraph) -> bool:
    """Check the declared support contract, not empirical causality or truth.

    A connected world->exposure->KPI path is required, not scattered supported
    labels. Only case-source-bound, explicitly SUPPORTED causal edges can count.
    """
    known = {s.source_id for s in case.sources}
    nodes = {n.node_id: n for n in graph.nodes}
    edges = [e for e in graph.edges
             if e.status is EdgeStatus.SUPPORTED
             and e.edge_type in {EdgeType.CAUSES, EdgeType.EXPOSES, EdgeType.IMPLIES}
             and set(e.evidence_refs) <= known]
    starts = [n.node_id for n in graph.nodes if n.node_type is NodeType.WORLD_STATE]
    stack = [(n, False, False) for n in starts]
    visited = set()
    while stack:
        node, has_exposure, has_cause = stack.pop()
        state = (node, has_exposure, has_cause)
        if state in visited:
            continue
        visited.add(state)
        for edge in edges:
            if edge.source_node != node:
                continue
            target = nodes[edge.target_node]
            exposed = has_exposure or (
                edge.edge_type is EdgeType.EXPOSES
                and target.node_type is NodeType.COMPANY_EXPOSURE
            )
            caused = has_cause or edge.edge_type is EdgeType.CAUSES
            if (target.node_id == case.primary_fundamental_variable
                    and target.node_type is NodeType.COMPANY_KPI
                    and edge.edge_type is EdgeType.IMPLIES and exposed and caused):
                return True
            stack.append((target.node_id, exposed, caused))
    return False


def compile_shadow_repricing_decision(
    *,
    case: RepricingCase,
    gap: ExpectationGap | None,
    context: RepricingContext,
    graph: RepricingGraph | None = None,
    dominant_contradiction: bool = False,
) -> ShadowRepricingDecision:
    validate_repricing_case(case)
    if not isinstance(dominant_contradiction, bool):
        raise TypeError("dominant_contradiction must be bool")
    if context.target_excluded_linkage.ticker != case.ticker:
        raise ValueError("context target differs from case target")
    if case.ticker in context.control_members:
        raise ValueError("context control contains target")
    if _parse_time(context.context_as_of) > _parse_time(case.as_of):
        raise ValueError("context exceeds case as_of")
    if gap is not None:
        if case.our_expectation is None or case.market_expectation is None:
            raise ValueError("gap requires both source-bound expectations")
        if (gap.variable_id != case.primary_fundamental_variable
                or gap != calculate_expectation_gap(case.our_expectation, case.market_expectation)):
            raise ValueError("gap does not match case expectations")

    warnings = list(context.warnings)
    supported_path = False
    if graph is None:
        warnings.append("causal graph not bound")
    else:
        validate_repricing_graph(graph)
        if graph.graph_id != case.graph_ref:
            raise ValueError("case is bound to a different causal graph")
        if _parse_time(graph.as_of) > _parse_time(case.as_of):
            raise ValueError("causal graph is future-dated relative to case")
        supported_path = _supported_path(case, graph)
    if not supported_path:
        warnings.append("supported causal transmission path missing")

    transmission_derived = (
        case.our_expectation is not None
        and case.our_expectation.derivation_method is RealityEstimateMethod.CAUSAL_TRANSMISSION
    )
    if not transmission_derived:
        warnings.append("our expectation is not transmission-derived")
    positive_gap = gap is not None and (
        gap.value > 0.0 if gap.value is not None else gap.low is not None and gap.low > 0.0
    )
    if gap is not None:
        if gap.low is not None and gap.high is not None and gap.low <= 0 <= gap.high:
            warnings.append("gap interval crosses zero")
        elif not positive_gap:
            warnings.append("expectation gap is not positive")
    else:
        warnings.append("decision-relevant expectation gap unavailable")
    catalyst_bound = bool(case.catalysts) and set(case.catalyst_refs) == {
        c.catalyst_id for c in case.catalysts
    }
    if not catalyst_bound:
        warnings.append("complete catalyst record missing")
    if any("ESTIMATED" in c.status for c in case.catalysts):
        warnings.append("catalyst date is estimated, not company-confirmed")

    if dominant_contradiction:
        status = "INVALIDATED"
    elif (not positive_gap or not context.causal_exposure_validated
            or not catalyst_bound or not supported_path or not transmission_derived):
        status = "RESEARCHING"
    else:
        status = "CANDIDATE"

    frozen_inputs = json_values({
        "case": asdict(case),
        "gap": None if gap is None else asdict(gap),
        "context": asdict(context),
        "graph": None if graph is None else asdict(graph),
        "dominant_contradiction": dominant_contradiction,
    })
    return ShadowRepricingDecision(
        case_hash=canonical_hash(frozen_inputs), as_of=case.as_of,
        ticker=case.ticker, theme_id=case.theme_id, expectation_gap=gap,
        catalyst_refs=case.catalyst_refs, catalysts=case.catalysts,
        tape_context=context.tape_assessment, scenarios=case.scenarios,
        strongest_counter_thesis=case.strongest_counter_thesis,
        invalidation_conditions=case.invalidation_conditions,
        key_unknowns=case.key_unknowns, status=status, warnings=tuple(warnings),
        frozen_inputs_json=json.dumps(frozen_inputs, sort_keys=True, allow_nan=False),
    )
