"""One-use synthetic E2 diagnostic. No production patching or oracle-bearing worker input."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import random
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent
E1_DIR = ROOT.parent / 'stop_e1'
sys.path.insert(0, str(E1_DIR))
import run_e1 as e1

SEED = 20260926
READERS = ('LATEST', 'SOURCE_BALANCED')
ORDERS = ('ORIGINAL', 'SHUFFLED')
POLICIES = ('FIRST_READY', 'FIXED_K', 'MAX_B')
FIELDS = ('net_debt_usd', 'ebitda_usd', 'maximum_leverage')


def verify_inherited():
    expected = {
        'run_e1.py': 'c0296f1598e2f368135d8f5245c845e66304e3bea3c581e7f7ea2aabf2678632',
        'fact_readout.py': '9d8227d1fc8b08dd5bd6b5482c9fca5df8f2b02dad16cf3ddd5b703a3bf6b3b1',
    }
    for name, sha in expected.items():
        if hashlib.sha256((E1_DIR / name).read_bytes()).hexdigest() != sha:
            raise RuntimeError('frozen source changed: ' + name)
    return {'g1_unchanged': True, 'e1_unchanged': True, 'sha256': expected}


def _validate(query, offers, reader):
    if reader not in READERS:
        raise ValueError('unknown reader')
    e1.read_facts(query, [])
    if not isinstance(offers, list):
        raise TypeError('offers must be a list')
    for offer in offers:
        if not isinstance(offer, dict) or set(offer) != {'body', 'family'}:
            raise ValueError('offers must contain only body and family')
        if not all(isinstance(offer[k], str) and offer[k].strip() for k in ('body', 'family')):
            raise ValueError('body and family must be nonempty strings')


def read_visible(query, offers, reader):
    """Source-balanced voting is a frozen alternative assumption, not a truth oracle."""
    _validate(query, offers, reader)
    if reader == 'LATEST':
        return e1.read_facts(query, [o['body'] for o in offers])
    eligible = [o for o in offers if e1.eligible(query, o['body'])]
    parent = {o['family']: o['family'] for o in eligible}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    # Exact copies link source families; repeated labels cannot multiply votes.
    owner = {}
    for offer in eligible:
        family, body = offer['family'], offer['body']
        if body in owner:
            a, b = find(family), find(owner[body])
            parent[a] = b
        else:
            owner[body] = family
    clusters = defaultdict(set)
    for offer in eligible:
        clusters[find(offer['family'])].add(offer['body'])
    votes = [e1.read_facts(query, sorted(bodies)) for bodies in clusters.values()]
    count = Counter(v['verdict'] for v in votes)
    winners = [v for v in sorted(e1.RESOLVED) if count[v] * 2 > len(votes)]
    facts = {}
    if winners:
        verdict = winners[0]
        candidates = [v for v in votes if v['verdict'] == verdict]
        candidates.sort(key=lambda v: (
            Fraction(v['facts']['net_debt_usd']) / Fraction(v['facts']['ebitda_usd']),
            *(Fraction(v['facts'][f]) for f in FIELDS)))
        facts = dict(candidates[(len(candidates) - 1) // 2]['facts'])
        reasons = ['strict_source_component_majority; representative_observed_report']
    elif count['CONFLICT'] or (count['WITHIN_LIMIT'] and count['ABOVE_LIMIT']):
        verdict, reasons = 'CONFLICT', ['no_strict_source_component_majority']
    else:
        verdict, reasons = 'UNKNOWN', ['insufficient_resolved_source_components']
    return {'verdict': verdict, 'facts': facts, 'reasons': reasons,
            'effective_sources': len(votes), 'vote_counts': dict(sorted(count.items()))}


def native_trace(request):
    if not isinstance(request, dict) or set(request) != {'query', 'offers', 'reader'}:
        raise ValueError('native request must contain only query, offers, reader')
    query, offers, reader = request['query'], request['offers'], request['reader']
    _validate(query, offers, reader)
    if query != e1.QUERY or len(offers) > 6:
        raise ValueError('native pilot supports the frozen query and at most six offers')
    if reader == 'LATEST':
        return e1.native_trace({'query': query, 'offers': offers})
    # The following intake/builder path preserves E1. Only the content readout differs.
    from decision_lab.evidence import EvidenceRecord
    from decision_lab.research_execution import (
        CompanyResearchSubmission, CompanyLinkageSubmission, ResearchEvidenceInput,
        ResearchEvidenceDirection, ResearchExecutionClosure, ResearchFinding,
        ResearchFindingKind, build_research_dossier)
    from decision_lab.research_execution_archive import build_research_dossier_archive_record
    from decision_lab.research_decision_readiness import assess_research_decision_readiness
    from decision_lab.research_decision_integration import evaluate_research_decision_admission
    from decision_lab.playbooks import route_playbooks
    work_archive, order, policy, fixture = e1.context()

    def at(t):
        return f'2026-09-20T20:00:{t:02d}+00:00'

    background = EvidenceRecord(
        evidence_id='synthetic:common-background', observed_at=e1.QUERY['as_of'], retrieved_at=at(0),
        market_asof=e1.QUERY['as_of'], ticker='AAA', theme=order.theme_id, source_type='sec_filing',
        source_ref='synthetic:common-background', fact_type='synthetic_background',
        payload=dict(e1.BACKGROUND), is_observed_fact=True).with_hash()
    inputs = [ResearchEvidenceInput(evidence=background, independent=False,
        direction=ResearchEvidenceDirection.SUPPORTING,
        dimensions=tuple(d for d in policy.industrials_company_dimensions if d != 'balance_sheet_strength'),
        target_ticker='AAA')]
    families, seen_bodies = set(), set()
    records, assessments, rows = [], [], []
    for step in range(len(offers) + 1):
        if step:
            offer = offers[step - 1]
            body, family = offer['body'], offer['family']
            bh = hashlib.sha256(body.encode()).hexdigest()
            if e1.eligible(query, body) and bh not in seen_bodies:
                one = e1.read_facts(query, [body])
                pub = next(line.split(':', 1)[1].strip() for line in body.splitlines()
                           if line.startswith('Published:'))
                raw = EvidenceRecord(
                    evidence_id='synthetic:raw:' + bh, observed_at=pub, retrieved_at=at(step),
                    market_asof=query['as_of'], ticker='AAA', theme=order.theme_id,
                    source_type='sec_filing', source_ref=f'synthetic:raw:{family}:{bh}',
                    fact_type='synthetic_disclosed_statement',
                    payload={'body': body, 'source_family': family}, is_observed_fact=True).with_hash()
                inputs.append(ResearchEvidenceInput(
                    evidence=raw, independent=family not in families,
                    direction=ResearchEvidenceDirection.SUPPORTING,
                    dimensions=('balance_sheet_strength',), target_ticker='AAA'))
                if one['verdict'] in e1.RESOLVED:
                    derived = EvidenceRecord(
                        evidence_id='synthetic:derived:' + bh, observed_at=at(step),
                        retrieved_at=at(step), market_asof=query['as_of'], ticker='AAA',
                        theme=order.theme_id, source_type='derived_feature',
                        source_ref=f'synthetic:calculation:{family}:{bh}',
                        fact_type='derived_ratio_from_disclosed_statement',
                        payload={'net_debt_to_ebitda': e1.ratio(one),
                                 'derived_from_source_hash': raw.source_hash},
                        is_observed_fact=False).with_hash()
                    inputs.append(ResearchEvidenceInput(
                        evidence=derived, independent=False,
                        direction=ResearchEvidenceDirection.SUPPORTING,
                        dimensions=('balance_sheet_strength',), target_ticker='AAA'))
                families.add(family)
                seen_bodies.add(bh)
        readout = read_visible(query, offers[:step], reader)
        facts = dict(e1.BACKGROUND)
        findings = ()
        if readout['verdict'] in e1.RESOLVED:
            facts['net_debt_to_ebitda'] = e1.ratio(readout)
        else:
            findings = (ResearchFinding(
                finding_id='leverage-unresolved', kind=ResearchFindingKind.UNRESOLVED,
                direction=None, dimension='balance_sheet_strength', target_ticker='AAA',
                statement=readout['verdict'], evidence_source_hashes=()),)
        hashes = tuple(i.evidence.source_hash for i in inputs)
        dossier = build_research_dossier(
            order, evidence_as_of=at(step), closure=ResearchExecutionClosure.CLOSED,
            evidence_inputs=tuple(inputs), findings=findings,
            company_submissions=(CompanyResearchSubmission(
                ticker='AAA', as_of=at(step), adapter_name='industrials_infrastructure',
                raw_facts=facts, evidence_source_hashes=hashes),),
            linkage_submissions=(CompanyLinkageSubmission(ticker='AAA', linkage=fixture._usable_linkage('AAA')),))
        record = build_research_dossier_archive_record(
            work_archive, dossier, prior_dossier_archive=records[-1] if records else None)
        records.append(record)
        readiness = assess_research_decision_readiness(tuple(records), record.archive_record_hash)
        assessments.append(readiness)
        admission = evaluate_research_decision_admission(tuple(records), readiness, 'AAA')
        native_route = None
        if admission.status.value == 'ADMITTED' and readout['verdict'] in e1.RESOLVED:
            native_route = asdict(route_playbooks(
                theme_key=True, tape_state='clean_retest', tape_stage='B3',
                fundamentals_intact=readout['verdict'] == 'WITHIN_LIMIT', world_confidence='normal'))
        rows.append({'step': step, 'readout': readout, 'readiness': readiness.status.value,
                     'admission': admission.status.value, 'independent_sources': dossier.independent_source_count,
                     'unsatisfied_dimensions': [r.dimension for r in dossier.unsatisfied_requirements],
                     'archive_hash': record.archive_record_hash, 'readiness_hash': readiness.readiness_assessment_hash,
                     'admission_hash': admission.admission_hash, 'native_route': native_route})
    return {'trace': rows, 'policy': asdict(policy),
            'native_records': [asdict(r) for r in records],
            'native_readiness': [asdict(a) for a in assessments]}


def _rng(namespace, regime_index, world_index):
    # Domain separation avoids the overlap caused by shifting E1 integer seeds by one.
    text = f'STOP_RESEARCH_E2|{namespace}|{SEED}|{regime_index}|{world_index}'
    return random.Random(int(hashlib.sha256(text.encode()).hexdigest(), 16))


def generate(n=32):
    """E1 mechanisms, fresh domain-separated worlds, two fixed acquisition orders."""
    visible, oracle = [], {}
    for ri, regime in enumerate(e1.REGIMES):
        for j in range(n):
            rng = _rng('world', ri, j)
            ebitda, ceiling = rng.randint(50, 200), rng.randint(2, 4)
            within = rng.random() < .5
            low, high = Fraction(ebitda * ceiling * 4, 5), Fraction(ebitda * ceiling * 6, 5)
            true_debt = low if within else high
            key = f'e2-{ri}-{j:03d}'
            oracle[key] = {'debt': str(true_debt), 'ebitda': str(ebitda), 'ceiling': str(ceiling),
                'verdict': 'WITHIN_LIMIT' if true_debt <= ebitda * ceiling else 'ABOVE_LIMIT'}
            persistent_correct = rng.random() < .8
            offers, last_body, last_debt, last_rev, last_family = [], '', low, 1, 'S1'
            for step in range(1, 7):
                u = rng.random()
                if step == 1:
                    kind = 'valid'
                elif regime == 'mixed':
                    kind = ('valid' if u < .45 else 'duplicate' if u < .65 else
                            'irrelevant' if u < .75 else 'future' if u < .85 else 'conflict')
                else:
                    kind = 'valid' if u < .7 else 'duplicate' if u < .9 else 'irrelevant'
                family = f'S{rng.randint(1, 4)}'
                probability = ([.55, .65, .75, .85, .9, .95][step - 1] if regime == 'improving'
                               else [.95, .9, .85, .75, .65, .55][step - 1]
                               if regime == 'deteriorating' else .8)
                correct = persistent_correct if regime == 'persistent' else rng.random() < probability
                reported = true_debt if correct else high if within else low
                if kind == 'duplicate':
                    body, family = last_body, last_family
                elif kind == 'conflict':
                    reported = high if last_debt == low else low
                    body = e1.disclosure(float(reported), ebitda, ceiling, last_rev)
                else:
                    body = e1.disclosure(float(reported), ebitda, ceiling, step,
                        company='BBB' if kind == 'irrelevant' else 'AAA', future=kind == 'future')
                if kind == 'valid':
                    last_body, last_debt, last_rev, last_family = body, reported, step, family
                offers.append({'body': body, 'family': family})
            shuffled = list(range(6))
            _rng('order', ri, j).shuffle(shuffled)
            for order_name, indices in (('ORIGINAL', list(range(6))), ('SHUFFLED', shuffled)):
                visible.append({'world': key, 'regime': regime, 'order': order_name,
                                'indices': indices,
                                'request': {'query': dict(e1.QUERY), 'offers': [dict(offers[i]) for i in indices]}})
    return visible, oracle


def _score(row, truth):
    verdict = row['readout']['verdict']
    admitted = row['admission'] == 'ADMITTED'
    return e1.outcome(verdict, admitted, truth)


def _row_loss(trace, step, truth):
    return e1.loss(_score(trace[step], truth), step)


def decompose(latest, source, truth):
    a = e1.choose_steps(latest)['FIRST_READY']
    b = e1.choose_steps(source)['FIRST_READY']
    la, lb = _row_loss(latest, a, truth), _row_loss(latest, b, truth)
    sa, sb = _row_loss(source, a, truth), _row_loss(source, b, truth)
    maximum = len(latest) - 1
    result = {'latest_stop': a, 'source_stop': b, 'total': sb - la,
              'reader_at_latest_stop': sa - la, 'time_after_source_reader': sb - sa,
              'time_before_reader_switch': lb - la, 'reader_at_source_stop': sb - lb,
              'latest_more_research': _row_loss(latest, maximum, truth) - la,
              'source_more_research': _row_loss(source, maximum, truth) - sb}
    result['reader_stop_interaction'] = result['source_more_research'] - result['latest_more_research']
    for x, y in (('reader_at_latest_stop', 'time_after_source_reader'),
                 ('time_before_reader_switch', 'reader_at_source_stop')):
        if abs(result['total'] - result[x] - result[y]) > 1e-10:
            raise RuntimeError('crossover accounting failed')
    return {k: round(v, 10) if isinstance(v, float) else v for k, v in result.items()}


def worker_results(jobs):
    payload = ''.join(e1.encode(job) + '\n' for job in jobs)
    run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'],
                         input=payload, text=True, capture_output=True, timeout=900)
    if run.returncode:
        raise RuntimeError(run.stderr)
    answers = [json.loads(line) for line in run.stdout.splitlines()]
    if len(answers) != len(jobs):
        raise RuntimeError('worker output count mismatch')
    return answers


def aggregate(rows):
    counts = Counter(r['outcome'] for r in rows)
    n = len(rows)
    issued = counts['CORRECT'] + counts['WRONG']
    return {'n': n, 'correct': counts['CORRECT'], 'wrong': counts['WRONG'], 'defer': counts['DEFER'],
            'no_admission': sum(not r['admitted'] for r in rows),
            'unknown_conflict': sum(r['verdict'] not in e1.RESOLVED for r in rows),
            'coverage': issued / n, 'conditional_error': counts['WRONG'] / issued if issued else None,
            'mean_queries': sum(r['queries'] for r in rows) / n,
            'mean_loss': sum(r['loss'] for r in rows) / n}


def save_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--verify-repeat', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'results')
    args = parser.parse_args()
    verify_inherited()
    if args.worker:
        for line in sys.stdin:
            if line.strip():
                print(e1.encode(native_trace(json.loads(line))), flush=True)
        return
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    ident = e1.identity()
    ident['inherited_instrument'] = verify_inherited()
    if args.verify_repeat:
        jobs = json.loads((out / 'worker_requests.json').read_text())
        again = worker_results(jobs)
        with gzip.open(out / 'native_outputs.json.gz', 'rt') as handle:
            original = json.load(handle)
        if original != again:
            raise RuntimeError('native rerun differs')
        e1.save(out / 'verification.json', {'status': 'E2_NATIVE_DETERMINISTIC_RERUN_PASS',
            'trajectories': len(again), 'native_output_digest': e1.digest(again),
            'all_records_readiness_admission_equal': True, 'production_modified': False})
        print('E2_NATIVE_DETERMINISTIC_RERUN_PASS', flush=True)
        return
    if (out / 'pre_run_freeze.json').exists():
        raise FileExistsError('use a fresh --output directory; original freeze is not overwritten')
    visible, oracle = generate()
    jobs = [{**v['request'], 'reader': reader} for v in visible for reader in READERS]
    freeze = {'seed': SEED, 'seed_namespace': 'STOP_RESEARCH_E2|world/order|seed|regime|index',
        'worlds_per_regime': 32, 'readers': READERS, 'orders': ORDERS, 'fixed_K': 3, 'max_B': 6,
        'protocol_sha256': hashlib.sha256((ROOT / 'PROTOCOL.md').read_bytes()).hexdigest(),
        'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'visible_hash': e1.digest(visible), 'oracle_hash': e1.digest(oracle),
        'worker_requests_hash': e1.digest(jobs), 'external_preregistration': False}
    e1.save(out / 'pre_run_freeze.json', freeze)
    e1.save(out / 'source_identity.json', ident)
    e1.save(out / 'visible_worlds.json', visible)
    e1.save(out / 'oracle_NOT_SENT_TO_WORKER.json', oracle)
    e1.save(out / 'worker_requests.json', jobs)
    print('FROZEN: 128 latent worlds, 2 orders, 2 readers; 512 native trajectories.', flush=True)
    answers = worker_results(jobs)
    with gzip.open(out / 'native_outputs.json.gz', 'wt') as handle:
        json.dump(answers, handle, sort_keys=True)
    rows, decompositions = [], []
    for i, case in enumerate(visible):
        truth_row = oracle[case['world']]
        truth = truth_row['verdict']
        expected = Fraction(truth_row['debt']) <= Fraction(truth_row['ebitda']) * Fraction(truth_row['ceiling'])
        assert expected == (truth == 'WITHIN_LIMIT')
        for rj, reader in enumerate(READERS):
            trace = answers[2 * i + rj]['trace']
            for policy, step in e1.choose_steps(trace).items():
                item = trace[step]
                scored = _score(item, truth)
                rows.append({'world': case['world'], 'regime': case['regime'], 'order': case['order'],
                    'reader': reader, 'policy': policy, 'queries': step,
                    'truth': truth, 'verdict': item['readout']['verdict'],
                    'admitted': int(item['admission'] == 'ADMITTED'), 'outcome': scored,
                    'shadow_outcome': e1.outcome(item['readout']['verdict'], True, truth),
                    'loss': round(e1.loss(scored, step), 8),
                    'action': item['native_route']['action'] if item['native_route'] else 'NO_ADMISSION'})
        decompositions.append({'world': case['world'], 'regime': case['regime'], 'order': case['order'],
            **decompose(answers[2 * i]['trace'], answers[2 * i + 1]['trace'], truth)})
    save_csv(out / 'policy_rows.csv', rows)
    e1.save(out / 'decomposition.json', decompositions)
    groups, sensitivity, interactions = [], [], []
    for regime in e1.REGIMES:
        for order in ORDERS:
            for reader in READERS:
                for policy in POLICIES:
                    rr = [r for r in rows if (r['regime'], r['order'], r['reader'], r['policy']) ==
                          (regime, order, reader, policy)]
                    group_key = {'regime': regime, 'order': order, 'reader': reader, 'policy': policy}
                    groups.append({**group_key, **aggregate(rr)})
                    for defer in (.1, .25, .5, 1):
                        for cost in (0, .01, .02, .05, .1):
                            sensitivity.append({**group_key, 'defer_penalty': defer, 'query_penalty': cost,
                                'mean_loss': sum(e1.loss(r['outcome'], r['queries'], defer, cost) for r in rr) / len(rr)})
            dd = [d for d in decompositions if d['regime'] == regime and d['order'] == order]
            keys = ('total', 'reader_at_latest_stop', 'time_after_source_reader',
                    'time_before_reader_switch', 'reader_at_source_stop', 'latest_more_research',
                    'source_more_research', 'reader_stop_interaction')
            interactions.append({'regime': regime, 'order': order, 'n': len(dd),
                'changed_stop_times': sum(d['latest_stop'] != d['source_stop'] for d in dd),
                **{k: sum(d[k] for d in dd) / len(dd) for k in keys}})
    pooled = [{'reader': reader, 'policy': policy,
               **aggregate([r for r in rows if r['reader'] == reader and r['policy'] == policy])}
              for reader in READERS for policy in POLICIES]
    e1.save(out / 'sensitivity.json', sensitivity)
    e1.save(out / 'groups.json', groups)
    e1.save(out / 'interactions.json', interactions)
    # Matched-budget contrasts are descriptive, with all deferrals retained.
    matched = []
    for regime in e1.REGIMES:
        for order in ORDERS:
            for policy in POLICIES:
                rr = {(r['world'], r['reader']): r for r in rows
                      if r['regime'] == regime and r['order'] == order and r['policy'] == policy}
                ids = sorted({k[0] for k in rr})
                changes = Counter(rr[(w, 'LATEST')]['outcome'] + '->' + rr[(w, 'SOURCE_BALANCED')]['outcome'] for w in ids)
                matched.append({'regime': regime, 'order': order, 'policy': policy,
                    'outcome_transitions': dict(sorted(changes.items())),
                    'source_minus_latest_mean_loss': sum(rr[(w, 'SOURCE_BALANCED')]['loss'] - rr[(w, 'LATEST')]['loss'] for w in ids) / len(ids)})
    e1.save(out / 'matched_reader_contrasts.json', matched)
    fullset_equal = True
    for i in range(0, len(visible), 2):
        assert visible[i]['world'] == visible[i + 1]['world']
        assert sorted(e1.encode(o) for o in visible[i]['request']['offers']) == sorted(e1.encode(o) for o in visible[i + 1]['request']['offers'])
        for reader_index in range(2):
            fullset_equal &= (answers[2 * i + reader_index]['trace'][-1]['readout'] ==
                              answers[2 * (i + 1) + reader_index]['trace'][-1]['readout'])
    # Equality is a reader fixed-set invariance gate, never a superiority condition.
    assert fullset_equal
    evidence_same = all(
        a['dossier']['evidence_bindings'] == b['dossier']['evidence_bindings']
        for i in range(len(visible))
        for a, b in zip(answers[2 * i]['native_records'], answers[2 * i + 1]['native_records']))
    assert evidence_same and len(rows) == 1536 and len(answers) == 512
    assert all(g['n'] == 32 and g['correct'] + g['wrong'] + g['defer'] == 32 for g in groups)
    example_index = next((i for i, d in enumerate(decompositions) if d['latest_stop'] != d['source_stop']), 0)
    e1.save(out / 'example.json', {'visible': visible[example_index],
        'oracle': oracle[visible[example_index]['world']], 'decomposition': decompositions[example_index],
        'latest_trace': answers[2 * example_index]['trace'],
        'source_trace': answers[2 * example_index + 1]['trace']})
    e1.save(out / 'summary.json', {
        'status': 'E2_NATIVE_READER_STOP_CROSSOVER_COMPLETE', 'latent_worlds': len(oracle),
        'world_order_pairs': len(visible), 'native_trajectories': len(answers),
        'native_snapshots': sum(len(a['trace']) for a in answers), 'policy_endpoints': len(rows),
        'unique_full_visible_requests': len({e1.digest(v['request']) for v in visible}),
        'fixed_set_readouts_order_invariant': bool(fullset_equal),
        'same_evidence_intake_across_readers': evidence_same,
        'pooled_equal_mixture_repeated_orders': pooled, 'decomposition_groups': interactions,
        'native_output_digest': e1.digest(answers), 'pre_run_freeze': freeze,
        'scope': {'real_companies': 0, 'LLM_calls': 0, 'production_modified': False,
                  'native_workorder_dossier_archive_progression_readiness_admission': True,
                  'native_router': True, 'native_decision_compiler': False},
        'limitations': ['128 latent worlds; orders and policy endpoints are repeated measurements',
            'designed synthetic regimes and declared source-family annotations',
            'SOURCE_BALANCED is not assumed superior or statistically independent',
            'different readers may change stopping time and factual coverage',
            'decomposition is reference-path dependent accounting, not unique natural causal effects',
            'synthetic common background/linkage and fixed CLOSED batches',
            'no adaptive source acquisition, true corporate due diligence, or financial returns']})
    print('E2_NATIVE_READER_STOP_CROSSOVER_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
