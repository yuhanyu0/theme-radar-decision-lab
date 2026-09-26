"""Recovered-plan hostile checks; synthetic mutations are not market observations."""
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
import yaml

from experiments.repricing_graph_v0_1.case_io import load_shadow_case
from experiments.repricing_graph_v0_1.gap import calculate_expectation_gap, summarize_scenarios
from experiments.repricing_graph_v0_1.model import ScenarioReturn
from experiments.repricing_graph_v0_1.shadow_case import compile_shadow_repricing_decision
from experiments.repricing_graph_v0_1.template import load_etn_template
from experiments.repricing_graph_v0_1.test_gap import _ours
from experiments.repricing_graph_v0_1.test_shadow_case import _context

ROOT = Path(__file__).parent
CASE = ROOT / 'cases/ETN_2026Q2_shadow.yaml'
TEMPLATE = ROOT / 'datacenter_etn_template.yaml'


def write(tmp_path, mutate):
    data = yaml.safe_load(CASE.read_text())
    mutate(data)
    p = tmp_path / 'case.yaml'
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


def test_nonfinite_estimate_rejected():
    with pytest.raises(ValueError, match='finite'):
        _ours(value=float('nan'))


def test_invalid_kind_rejected_not_silently_accepted():
    with pytest.raises((ValueError, TypeError), match='kind'):
        _ours(kind='POINT')


def test_yaml_false_string_not_truthy_boolean(tmp_path):
    p = write(tmp_path, lambda d: d['our_expectation'].update(probability_is_calibrated='false'))
    with pytest.raises((ValueError, TypeError), match='bool'):
        load_shadow_case(p)


def test_estimate_cannot_predate_its_source(tmp_path):
    p = write(tmp_path, lambda d: d['market_expectation'].update(available_at='2026-09-24T00:00:00+00:00'))
    with pytest.raises(ValueError, match='source availability'):
        load_shadow_case(p)


def test_invented_gap_cannot_enter_compiler():
    c = load_shadow_case(CASE)
    gap = replace(calculate_expectation_gap(c.our_expectation, c.market_expectation), low=5, high=8)
    with pytest.raises(ValueError, match='gap'):
        compile_shadow_repricing_decision(case=c, gap=gap, context=_context(), graph=load_etn_template(TEMPLATE))


def test_cross_target_context_rejected():
    c = load_shadow_case(CASE)
    ctx = _context()
    ctx = replace(ctx, target_excluded_linkage=replace(ctx.target_excluded_linkage, ticker='VRT'))
    with pytest.raises(ValueError, match='target'):
        compile_shadow_repricing_decision(case=c, gap=None, context=ctx)


def test_future_context_rejected():
    c = load_shadow_case(CASE)
    with pytest.raises(ValueError, match='context'):
        compile_shadow_repricing_decision(case=c, gap=None, context=replace(_context(), context_as_of='2026-09-26T20:00:00+00:00'))


def test_valuation_assumptions_are_preserved_and_hashed(tmp_path):
    def mut(d):
        d['market_expectation'].update(method='PRICE_IMPLIED', valuation_assumptions={'pe': 25.0})
    c = load_shadow_case(write(tmp_path, mut))
    d1 = compile_shadow_repricing_decision(case=c, gap=None, context=_context())
    def mut2(d):
        d['market_expectation'].update(method='PRICE_IMPLIED', valuation_assumptions={'pe': 30.0})
    c2 = load_shadow_case(write(tmp_path, mut2))
    d2 = compile_shadow_repricing_decision(case=c2, gap=None, context=_context())
    assert d1.case_hash != d2.case_hash


def test_calibrated_scenario_weights_cannot_be_arbitrary_scores():
    with pytest.raises(ValueError, match='calibrated'):
        summarize_scenarios((ScenarioReturn('bear', 1, -.1, '20d', 'x', ('x',), True),
                             ScenarioReturn('bull', 3, .1, '20d', 'x', ('x',), True)))


def test_full_input_source_and_catalyst_content_survive_loader():
    c = load_shadow_case(CASE)
    assert len(c.sources) == 3 and len(c.catalysts) == 1
    assert c.sources[0].source_id == 'etn_q2_release'
    assert '13.40' in c.sources[0].payload_json
    assert c.catalysts[0].expected_date_or_window == '2026-10-30/2026-11-04'


def test_benchmark_calendar_mismatch_is_not_misreported_as_excess_return():
    from experiments.repricing_graph_v0_1.evaluate import evaluate_shadow_case
    c = load_shadow_case(CASE)
    d = compile_shadow_repricing_decision(case=c, gap=None, context=_context())
    idx = pd.bdate_range('2026-09-25', periods=65)
    prices = pd.Series(range(100, 165), index=idx, dtype=float)
    spy = prices.drop(idx[5])
    with pytest.raises(ValueError, match='session'):
        evaluate_shadow_case(decision=d, close=prices, spy_close=spy)


def supported_example():
    from experiments.repricing_graph_v0_1.model import EdgeStatus, EdgeType, RealityEstimateMethod
    c = load_shadow_case(CASE)
    g = load_etn_template(TEMPLATE)
    g = replace(g, edges=tuple(replace(e, status=EdgeStatus.SUPPORTED,
        evidence_refs=('etn_q2_release',), provenance=('synthetic-test-only',))
        if e.edge_type in {EdgeType.CAUSES, EdgeType.EXPOSES, EdgeType.IMPLIES} else e
        for e in g.edges))
    c = replace(c, our_expectation=replace(c.our_expectation, low=14., high=14.2,
        derivation_method=RealityEstimateMethod.CAUSAL_TRANSMISSION))
    return c, g


def test_supported_positive_synthetic_case_can_be_candidate():
    c, g = supported_example()
    d = compile_shadow_repricing_decision(case=c, gap=calculate_expectation_gap(
        c.our_expectation, c.market_expectation), context=_context(), graph=g)
    assert d.status == 'CANDIDATE'


def test_zero_crossing_gap_not_positive_alpha_candidate():
    c, g = supported_example()
    c = replace(c, our_expectation=replace(c.our_expectation, low=13.4, high=13.6))
    d = compile_shadow_repricing_decision(case=c, gap=calculate_expectation_gap(
        c.our_expectation, c.market_expectation), context=_context(), graph=g)
    assert d.status == 'RESEARCHING'


def test_supported_label_with_unbound_causal_source_does_not_promote():
    c, g = supported_example()
    g = replace(g, edges=tuple(replace(e, evidence_refs=('not-in-source-registry',)) for e in g.edges))
    d = compile_shadow_repricing_decision(case=c, gap=calculate_expectation_gap(
        c.our_expectation, c.market_expectation), context=_context(), graph=g)
    assert d.status == 'RESEARCHING'


def test_frozen_input_payload_and_decision_are_self_consistent():
    import json
    from decision_lab.ledger import canonical_hash
    c = load_shadow_case(CASE)
    d = compile_shadow_repricing_decision(case=c, gap=None, context=_context())
    assert canonical_hash(json.loads(d.frozen_inputs_json)) == d.case_hash
    assert len(json.loads(d.frozen_inputs_json)['case']['sources']) == 3


def test_no_invented_confidence_needed_for_source_backed_estimate():
    assert _ours(confidence=None).confidence is None


def test_missing_forecast_is_a_valid_researching_record(tmp_path):
    c = load_shadow_case(write(tmp_path, lambda d: d.update(our_expectation=None)))
    d = compile_shadow_repricing_decision(case=c, gap=None, context=_context())
    assert d.status == 'RESEARCHING'


def test_catalyst_cannot_be_known_before_its_source(tmp_path):
    p = write(tmp_path, lambda d: d['catalysts'][0].update(known_at='2026-09-24T00:00:00+00:00'))
    with pytest.raises(ValueError, match='source availability'):
        load_shadow_case(p)


def test_calibrated_marginals_do_not_calibrate_interval_difference():
    from experiments.repricing_graph_v0_1.test_gap import _market
    from experiments.repricing_graph_v0_1.model import EstimateKind
    a = _ours(kind=EstimateKind.INTERVAL, value=None, low=10, high=12,
              probability_is_calibrated=True)
    b = _market(probability_is_calibrated=True)
    assert not calculate_expectation_gap(a, b).probability_is_calibrated


def test_native_numpy_boolean_survives_exact_json_boundary():
    import json
    import numpy as np
    c = load_shadow_case(CASE)
    ctx = _context()
    ctx = replace(ctx, tape_assessment=replace(ctx.tape_assessment, higher_low=np.bool_(True)))
    d = compile_shadow_repricing_decision(case=c, gap=None, context=ctx)
    assert json.loads(d.frozen_inputs_json)['context']['tape_assessment']['higher_low'] is True
