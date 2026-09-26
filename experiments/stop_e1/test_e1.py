import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


def module():
    assert importlib.util.find_spec('run_e1') is not None, 'E1 instrument is not implemented'
    return importlib.import_module('run_e1')


def request(debts=(200, 200), families=('A', 'B'), revisions=(1, 2)):
    m = module()
    return {'query': dict(m.QUERY), 'offers': [
        {'body': m.disclosure(d, 100, 3, r), 'family': f}
        for d, f, r in zip(debts, families, revisions)
    ]}


def test_native_gate_can_be_ready_for_wrong_report():
    m = module()
    result = m.native_trace(request())
    assert result['trace'][-1]['readiness'] == 'READY'
    assert m.outcome('WITHIN_LIMIT', True, 'ABOVE_LIMIT') == 'WRONG'


def test_default_policy_is_not_weakened():
    m = module()
    result = m.native_trace(request())
    assert result['policy']['minimum_independent_sources'] == 2
    assert result['policy']['minimum_independent_sources_per_company'] == 1
    assert result['policy']['require_usable_linkage_for_company'] is True
    assert len(result['policy']['industrials_company_dimensions']) == 10


def test_repeated_source_does_not_manufacture_independence():
    result = module().native_trace(request(families=('A', 'A')))
    assert result['trace'][-1]['independent_sources'] == 1
    assert result['trace'][-1]['readiness'] == 'NOT_READY'


def test_unknown_and_conflict_defer():
    m = module()
    result = m.native_trace(request(debts=(200, 400), revisions=(1, 1)))
    assert result['trace'][-1]['readout']['verdict'] == 'CONFLICT'
    assert result['trace'][-1]['readiness'] == 'NOT_READY'
    assert m.outcome('UNKNOWN', False, 'WITHIN_LIMIT') == 'DEFER'


def test_future_is_not_available():
    q = request()
    q['offers'][1]['body'] = q['offers'][1]['body'].replace('2026-09-20', '2026-09-21')
    result = module().native_trace(q)
    assert result['trace'][-1]['independent_sources'] == 1
    assert result['trace'][-1]['readiness'] == 'NOT_READY'


def test_only_visible_prefix_is_used():
    m = module()
    q = request()
    full = m.native_trace(q)
    short = m.native_trace({'query': q['query'], 'offers': q['offers'][:1]})
    assert full['trace'][:2] == short['trace']


def test_no_ready_fallback_is_defer_at_budget():
    m = module()
    result = m.native_trace(request(families=('A', 'A')))
    choices = m.choose_steps(result['trace'], fixed=1)
    assert choices == {'FIRST_READY': 2, 'FIXED_K': 1, 'MAX_B': 2}
    assert result['trace'][choices['FIRST_READY']]['admission'] == 'BLOCKED_NOT_READY'


def test_earliest_ready_not_latest():
    m = module()
    q = request(debts=(200, 200, 400), families=('A', 'B', 'C'), revisions=(1, 2, 3))
    result = m.native_trace(q)
    assert m.choose_steps(result['trace'], fixed=3)['FIRST_READY'] == 2
    assert result['trace'][3]['readout']['verdict'] == 'ABOVE_LIMIT'


def test_outcomes_cannot_enter_native_request():
    q = request()
    q['truth'] = 'WITHIN_LIMIT'
    with pytest.raises(ValueError, match='query and offers'):
        module().native_trace(q)


def test_native_deterministic_replay():
    m = module()
    assert m.native_trace(request()) == m.native_trace(request())


def test_generator_and_truth_separate():
    m = module()
    visible, oracle = m.generate(2)
    assert (visible, oracle) == m.generate(2)
    assert len(visible) == len(oracle) == 8
    for c in visible:
        assert set(c['request']) == {'query', 'offers'}
        assert 'truth' not in str(c['request']).lower()
        assert len(c['request']['offers']) == 6
        assert oracle[c['id']]['verdict'] in {'WITHIN_LIMIT', 'ABOVE_LIMIT'}


def test_loss_and_deferral():
    m = module()
    assert m.loss('CORRECT', 3, .25, .02) == pytest.approx(.06)
    assert m.loss('WRONG', 3, .25, .02) == pytest.approx(1.06)
    assert m.loss('DEFER', 3, .25, .02) == pytest.approx(.31)


def test_native_orphan_fork_and_stale_rejected():
    m = module()
    checks = m.structural_controls(request())
    assert all(checks.values()), checks


def test_g1_reader_exact_source():
    import hashlib
    module()
    digest = hashlib.sha256(Path(__file__).with_name('fact_readout.py').read_bytes()).hexdigest()
    assert digest == '9d8227d1fc8b08dd5bd6b5482c9fca5df8f2b02dad16cf3ddd5b703a3bf6b3b1'
