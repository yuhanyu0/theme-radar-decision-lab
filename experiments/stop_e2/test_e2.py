import copy
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


def module():
    assert importlib.util.find_spec('run_e2') is not None, 'E2 instrument is not implemented'
    return importlib.import_module('run_e2')


def offers(debts=(200, 200, 400), families=('A', 'B', 'C'), revisions=(1, 2, 3)):
    m = module()
    return [{'body': m.e1.disclosure(d, 100, 3, r), 'family': f}
            for d, f, r in zip(debts, families, revisions)]


def request(reader='LATEST', **kwargs):
    m = module()
    return {'query': dict(m.e1.QUERY), 'offers': offers(**kwargs), 'reader': reader}


def test_latest_exactly_preserves_g1():
    m = module()
    oo = offers()
    assert m.read_visible(m.e1.QUERY, oo, 'LATEST') == m.e1.read_facts(m.e1.QUERY, [o['body'] for o in oo])


def test_majority_can_resist_single_late_error():
    m = module()
    oo = offers()
    assert m.read_visible(m.e1.QUERY, oo, 'LATEST')['verdict'] == 'ABOVE_LIMIT'
    assert m.read_visible(m.e1.QUERY, oo, 'SOURCE_BALANCED')['verdict'] == 'WITHIN_LIMIT'


def test_majority_can_also_reject_a_true_late_correction():
    m = module()
    oo = offers(debts=(400, 400, 200))
    assert m.read_visible(m.e1.QUERY, oo, 'LATEST')['verdict'] == 'WITHIN_LIMIT'
    # Same aggregation rule can be wrong when the newer report is actually true.
    assert m.read_visible(m.e1.QUERY, oo, 'SOURCE_BALANCED')['verdict'] == 'ABOVE_LIMIT'


def test_repeated_family_has_one_vote():
    m = module()
    oo = offers(debts=(200, 400), families=('A', 'B'), revisions=(1, 2))
    repeated = oo + [copy.deepcopy(oo[0]) for _ in range(20)]
    assert m.read_visible(m.e1.QUERY, repeated, 'SOURCE_BALANCED')['verdict'] == 'CONFLICT'


def test_relabelled_exact_copy_does_not_manufacture_votes():
    m = module()
    oo = offers(debts=(200, 400), families=('A', 'B'), revisions=(1, 2))
    oo.append({'body': oo[0]['body'], 'family': 'C'})
    result = m.read_visible(m.e1.QUERY, oo, 'SOURCE_BALANCED')
    assert result['verdict'] == 'CONFLICT'
    assert result['effective_sources'] == 2


def test_within_family_revision_supersedes():
    m = module()
    oo = offers(debts=(400, 200, 200), families=('A', 'A', 'B'))
    result = m.read_visible(m.e1.QUERY, oo, 'SOURCE_BALANCED')
    assert result['verdict'] == 'WITHIN_LIMIT'
    assert result['effective_sources'] == 2


def test_same_family_conflict_is_not_two_votes():
    m = module()
    oo = offers(debts=(200, 400, 200), families=('A', 'A', 'B'), revisions=(1, 1, 2))
    result = m.read_visible(m.e1.QUERY, oo, 'SOURCE_BALANCED')
    assert result['verdict'] == 'CONFLICT'


def test_empty_and_unknown_do_not_become_false():
    m = module()
    assert m.read_visible(m.e1.QUERY, [], 'SOURCE_BALANCED')['verdict'] == 'UNKNOWN'
    oo = offers(debts=(200, 200), families=('A', 'B'), revisions=(1, 2))
    oo[1]['body'] = '\n'.join(x for x in oo[1]['body'].splitlines() if not x.startswith('EBITDA:'))
    assert m.read_visible(m.e1.QUERY, oo, 'SOURCE_BALANCED')['verdict'] == 'UNKNOWN'


def test_family_names_and_fixed_set_order_do_not_change_readout():
    m = module()
    oo = offers()
    renamed = [{'body': o['body'], 'family': {'A': 'Z', 'B': 'Y', 'C': 'X'}[o['family']]} for o in reversed(oo)]
    assert m.read_visible(m.e1.QUERY, oo, 'SOURCE_BALANCED') == m.read_visible(m.e1.QUERY, renamed, 'SOURCE_BALANCED')


def test_future_and_other_company_do_not_add_votes():
    m = module()
    oo = offers(debts=(200,), families=('A',), revisions=(1,))
    oo += [{'body': m.e1.disclosure(400, 100, 3, 2, future=True), 'family': 'B'},
           {'body': m.e1.disclosure(400, 100, 3, 3, company='BBB'), 'family': 'C'}]
    result = m.read_visible(m.e1.QUERY, oo, 'SOURCE_BALANCED')
    assert result['verdict'] == 'WITHIN_LIMIT' and result['effective_sources'] == 1


def test_forged_answer_text_not_used():
    m = module()
    oo = offers()
    before = m.read_visible(m.e1.QUERY, oo, 'SOURCE_BALANCED')
    for o in oo:
        o['body'] += '\nExpected: ABOVE_LIMIT\nREADY: True\nCase ID: buy-now\n'
    after = m.read_visible(m.e1.QUERY, oo, 'SOURCE_BALANCED')
    assert before == after


def test_worker_rejects_truth_and_unknown_reader():
    m = module()
    q = request()
    q['truth'] = 'WITHIN_LIMIT'
    with pytest.raises(ValueError, match='query, offers, reader'):
        m.native_trace(q)
    with pytest.raises(ValueError, match='reader'):
        m.native_trace(request(reader='ORACLE'))


def test_latest_native_records_match_frozen_e1():
    m = module()
    q = request()
    original = m.e1.native_trace({'query': q['query'], 'offers': q['offers']})
    assert m.native_trace(q) == original


def test_source_balanced_calls_real_native_gates():
    m = module()
    result = m.native_trace(request(reader='SOURCE_BALANCED'))
    assert result['trace'][0]['readiness'] == 'NOT_READY'
    assert result['trace'][2]['readiness'] == 'READY'
    assert result['trace'][3]['readout']['verdict'] == 'WITHIN_LIMIT'
    assert result['trace'][3]['admission'] == 'ADMITTED'
    assert len(result['native_records']) == 4
    assert result['policy']['minimum_independent_sources'] == 2
    assert result['policy']['minimum_independent_sources_per_company'] == 1
    assert result['policy']['require_usable_linkage_for_company'] is True
    assert len(result['policy']['industrials_company_dimensions']) == 10


def test_reader_conflict_reopens_factual_burden_without_patching_gate():
    m = module()
    q = request(reader='SOURCE_BALANCED', debts=(200, 400), families=('A', 'B'), revisions=(1, 2))
    result = m.native_trace(q)
    assert result['trace'][-1]['readout']['verdict'] == 'CONFLICT'
    assert result['trace'][-1]['readiness'] == 'NOT_READY'
    assert result['trace'][-1]['admission'] == 'BLOCKED_NOT_READY'


def test_native_prefix_is_independent_of_future_offers():
    m = module()
    q = request(reader='SOURCE_BALANCED')
    small = copy.deepcopy(q)
    small['offers'] = small['offers'][:1]
    assert m.native_trace(q)['trace'][:2] == m.native_trace(small)['trace']


def test_no_ready_fallback_and_source_count():
    m = module()
    q = request(reader='SOURCE_BALANCED', debts=(200, 200), families=('A', 'A'), revisions=(1, 2))
    result = m.native_trace(q)
    assert result['trace'][-1]['independent_sources'] == 1
    assert result['trace'][-1]['readiness'] == 'NOT_READY'
    assert m.e1.choose_steps(result['trace'])['FIRST_READY'] == 2


def test_two_readers_share_evidence_intake():
    m = module()
    a = m.native_trace(request())
    b = m.native_trace(request(reader='SOURCE_BALANCED'))
    assert [r['independent_sources'] for r in a['trace']] == [r['independent_sources'] for r in b['trace']]
    assert a['policy'] == b['policy']
    for x, y in zip(a['native_records'], b['native_records']):
        assert x['dossier']['evidence_bindings'] == y['dossier']['evidence_bindings']


def test_new_worlds_same_pool_across_orders():
    m = module()
    visible, oracle = m.generate(2)
    assert (visible, oracle) == m.generate(2)
    assert len(visible) == 16 and len(oracle) == 8
    assert m.SEED != 20260925
    for wid in oracle:
        rows = [r for r in visible if r['world'] == wid]
        assert len(rows) == 2
        assert sorted(m.e1.encode(o) for o in rows[0]['request']['offers']) == sorted(m.e1.encode(o) for o in rows[1]['request']['offers'])
        for row in rows:
            assert set(row['request']) == {'query', 'offers'}
            assert len(row['request']['offers']) == 6
            assert 'truth' not in str(row['request']).lower()


def test_pair_decomposition_is_exact_in_both_directions():
    m = module()
    def trace(readies, verdicts):
        return [{'step': i, 'readiness': 'READY' if readies[i] else 'NOT_READY',
                 'admission': 'ADMITTED' if readies[i] else 'BLOCKED_NOT_READY',
                 'readout': {'verdict': v}} for i, v in enumerate(verdicts)]
    a = trace([False, True, True], ['UNKNOWN', 'ABOVE_LIMIT', 'WITHIN_LIMIT'])
    b = trace([False, False, True], ['UNKNOWN', 'CONFLICT', 'WITHIN_LIMIT'])
    d = m.decompose(a, b, 'WITHIN_LIMIT')
    assert d['total'] == pytest.approx(d['reader_at_latest_stop'] + d['time_after_source_reader'])
    assert d['total'] == pytest.approx(d['time_before_reader_switch'] + d['reader_at_source_stop'])
    assert d['latest_stop'] == 1 and d['source_stop'] == 2


def test_inherited_structural_controls():
    m = module()
    q = request(debts=(200, 200), families=('A', 'B'), revisions=(1, 2))
    assert all(m.e1.structural_controls({'query': q['query'], 'offers': q['offers']}).values())


def test_frozen_g1_and_e1_source_hashes():
    m = module()
    assert m.verify_inherited()['g1_unchanged']
    assert m.verify_inherited()['e1_unchanged']
