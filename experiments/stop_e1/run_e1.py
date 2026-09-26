"""Narrow synthetic stopping experiment; native package is never replaced or patched."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import random
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, replace
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from fact_readout import _utc, read_facts

BASE = 'c5866ad8f09a472cf631a764f911547c05d337d9'
QUERY = {'company': 'AAA', 'period': '2026H1', 'as_of': '2026-09-20T19:00:00Z'}
REGIMES = ('persistent', 'improving', 'deteriorating', 'mixed')
BACKGROUND = {'revenue_growth': .1, 'gross_margin': .3, 'backlog_growth': .1,
              'order_growth': .1, 'capex_to_sales': .1, 'fcf_margin': .1,
              'top_customer_share': .2, 'guidance_revision': .02}
RESOLVED = {'WITHIN_LIMIT', 'ABOVE_LIMIT'}
ROOT = Path(__file__).resolve().parent


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def disclosure(debt, ebitda, limit, revision, company='AAA', future=False):
    day = '21' if future else '20'
    return (f'Company: {company}\nPeriod: 2026H1\n'
            f'Published: 2026-09-{day}T18:00:{revision:02d}Z\nRevision: {revision}\n'
            f'Net debt: USD {debt} million\nEBITDA: USD {ebitda} million\n'
            f'Maximum leverage: {limit} x\n')


def generate(n=32):
    """Truth sampled first; worker request excludes case IDs, regimes and oracle."""
    visible, oracle = [], {}
    for ri, regime in enumerate(REGIMES):
        for j in range(n):
            rng = random.Random(20260925 + ri * 100000 + j)
            ebitda, ceiling = rng.randint(50, 200), rng.randint(2, 4)
            within = rng.random() < .5
            low = Fraction(ebitda * ceiling * 4, 5)
            high = Fraction(ebitda * ceiling * 6, 5)
            true_debt = low if within else high
            key = f'{ri}-{j:03d}'
            oracle[key] = {'debt': str(true_debt), 'ebitda': str(ebitda),
                           'ceiling': str(ceiling),
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
                    body = disclosure(float(reported), ebitda, ceiling, last_rev)
                else:
                    body = disclosure(float(reported), ebitda, ceiling, step,
                                      company='BBB' if kind == 'irrelevant' else 'AAA',
                                      future=kind == 'future')
                if kind == 'valid':
                    last_body, last_debt, last_rev, last_family = body, reported, step, family
                offers.append({'body': body, 'family': family})
            visible.append({'id': key, 'regime': regime,
                            'request': {'query': dict(QUERY), 'offers': offers}})
    return visible, oracle


@lru_cache(maxsize=1)
def context():
    from decision_lab.research_execution import ResearchWorkOrderPolicy, ResearchMode, build_research_work_order
    from decision_lab.research_execution_archive import build_research_work_order_archive_record
    import decision_lab
    repo = Path(decision_lab.__file__).resolve().parents[2]
    path = repo / 'tests/test_research_decision_integration.py'
    spec = importlib.util.spec_from_file_location('_e1_native_fixture', path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    replay, package = fixture._replay_archive_and_package()
    raw = ResearchWorkOrderPolicy()
    policy = replace(raw, **{name: tuple(sorted(getattr(raw, name))) for name in (
        'theme_reassessment_dimensions', 'industrials_company_dimensions', 'biotech_company_dimensions')})
    order = build_research_work_order(replay, package.definition.theme_id, ResearchMode.COMPANY_DEEP_DIVE,
                                     theme_package=package, target_tickers=('AAA',), policy=policy)
    archive = build_research_work_order_archive_record(replay, order, work_order_policy=policy)
    return archive, order, policy, fixture


def eligible(query, body):
    headers = dict(line.split(':', 1) for line in body.splitlines() if ':' in line)
    return (headers.get('Company', '').strip() == query['company']
            and headers.get('Period', '').strip() == query['period']
            and _utc(headers['Published']) <= _utc(query['as_of']))


def ratio(readout):
    return float(Fraction(readout['facts']['net_debt_usd']) / Fraction(readout['facts']['ebitda_usd']))


def native_trace(request, retain=False):
    if not isinstance(request, dict) or set(request) != {'query', 'offers'}:
        raise ValueError('native request must contain only query and offers')
    query, offers = request['query'], request['offers']
    read_facts(query, [])  # schema and timestamp validation
    if any(set(o) != {'body', 'family'} for o in offers):
        raise ValueError('offers must contain only body and family')
    from decision_lab.evidence import EvidenceRecord
    from decision_lab.research_execution import (
        CompanyResearchSubmission, CompanyLinkageSubmission, ResearchEvidenceInput,
        ResearchEvidenceDirection, ResearchExecutionClosure, ResearchFinding,
        ResearchFindingKind, build_research_dossier)
    from decision_lab.research_execution_archive import build_research_dossier_archive_record
    from decision_lab.research_decision_readiness import assess_research_decision_readiness
    from decision_lab.research_decision_integration import evaluate_research_decision_admission
    from decision_lab.playbooks import route_playbooks
    work_archive, order, policy, fixture = context()
    at = lambda t: f'2026-09-20T20:00:{t:02d}+00:00'
    background = EvidenceRecord(
        evidence_id='synthetic:common-background', observed_at=QUERY['as_of'], retrieved_at=at(0),
        market_asof=QUERY['as_of'], ticker='AAA', theme=order.theme_id, source_type='sec_filing',
        source_ref='synthetic:common-background', fact_type='synthetic_background',
        payload=dict(BACKGROUND), is_observed_fact=True).with_hash()
    inputs = [ResearchEvidenceInput(evidence=background, independent=False,
                                   direction=ResearchEvidenceDirection.SUPPORTING,
                                   dimensions=tuple(d for d in policy.industrials_company_dimensions
                                                    if d != 'balance_sheet_strength'), target_ticker='AAA')]
    families, seen_bodies = set(), set()
    records, assessments, rows = [], [], []
    for step in range(len(offers) + 1):
        if step:
            offer = offers[step - 1]
            body, family = offer['body'], offer['family']
            bh = hashlib.sha256(body.encode()).hexdigest()
            if eligible(query, body) and bh not in seen_bodies:
                one = read_facts(query, [body])
                payload = {'body': body, 'source_family': family}
                if one['verdict'] in RESOLVED:
                    payload['net_debt_to_ebitda'] = ratio(one)
                pub = next(line.split(':', 1)[1].strip() for line in body.splitlines()
                           if line.startswith('Published:'))
                evidence = EvidenceRecord(
                    evidence_id='synthetic:' + bh, observed_at=pub, retrieved_at=at(step),
                    market_asof=query['as_of'], ticker='AAA', theme=order.theme_id,
                    source_type='sec_filing', source_ref=f'synthetic:{family}:{bh}',
                    fact_type='synthetic_disclosure_with_derived_ratio', payload=payload,
                    is_observed_fact=False).with_hash()
                inputs.append(ResearchEvidenceInput(
                    evidence=evidence, independent=family not in families,
                    direction=ResearchEvidenceDirection.SUPPORTING,
                    dimensions=('balance_sheet_strength',), target_ticker='AAA'))
                families.add(family)
                seen_bodies.add(bh)
        readout = read_facts(query, [o['body'] for o in offers[:step]])
        facts = dict(BACKGROUND)
        findings = ()
        if readout['verdict'] in RESOLVED:
            facts['net_debt_to_ebitda'] = ratio(readout)
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
        if admission.status.value == 'ADMITTED' and readout['verdict'] in RESOLVED:
            native_route = asdict(route_playbooks(theme_key=True, tape_state='clean_retest', tape_stage='B3',
                                                fundamentals_intact=readout['verdict'] == 'WITHIN_LIMIT',
                                                world_confidence='normal'))
        rows.append({'step': step, 'readout': readout, 'readiness': readiness.status.value,
                     'admission': admission.status.value, 'independent_sources': dossier.independent_source_count,
                     'unsatisfied_dimensions': [r.dimension for r in dossier.unsatisfied_requirements],
                     'archive_hash': record.archive_record_hash, 'readiness_hash': readiness.readiness_assessment_hash,
                     'admission_hash': admission.admission_hash, 'native_route': native_route})
    result = {'trace': rows, 'policy': asdict(policy),
              'native_records': [asdict(r) for r in records],
              'native_readiness': [asdict(a) for a in assessments]}
    if retain:
        result['_records'], result['_assessments'] = records, assessments
    return result


def choose_steps(trace, fixed=3):
    maximum = len(trace) - 1
    first = next((r['step'] for r in trace if r['readiness'] == 'READY'), maximum)
    return {'FIRST_READY': first, 'FIXED_K': min(fixed, maximum), 'MAX_B': maximum}


def outcome(verdict, admitted, truth):
    if not admitted or verdict not in RESOLVED:
        return 'DEFER'
    return 'CORRECT' if verdict == truth else 'WRONG'


def loss(result, acquisitions, defer=.25, cost=.02):
    return (1.0 if result == 'WRONG' else defer if result == 'DEFER' else 0.0) + cost * acquisitions


def structural_controls(request):
    from decision_lab.research_decision_readiness import assess_research_decision_readiness
    from decision_lab.research_decision_integration import evaluate_research_decision_admission
    from decision_lab.research_execution_archive import build_research_dossier_archive_record
    result = native_trace(request, retain=True)
    records, assessments = result['_records'], result['_assessments']
    last, work = records[-1], records[-1].work_order_archive
    orphan = assess_research_decision_readiness((last,), last.archive_record_hash)
    sibling = build_research_dossier_archive_record(work, last.dossier, prior_dossier_archive=records[0])
    fork_records = (*records, sibling)
    fork = assess_research_decision_readiness(fork_records, last.archive_record_hash)
    stale_rejected = False
    try:
        evaluate_research_decision_admission(fork_records, assessments[-1], 'AAA')
    except ValueError:
        stale_rejected = True
    return {'orphan_indeterminate': orphan.status.value == 'INDETERMINATE',
            'fork_indeterminate': fork.status.value == 'INDETERMINATE',
            'stale_rejected': stale_rejected}


def identity():
    import decision_lab
    repo = Path(decision_lab.__file__).resolve().parents[2]
    changed = subprocess.check_output(['git', 'diff', '--name-only', BASE, '--',
                                       'src', 'tests', 'schemas', 'pyproject.toml'], cwd=repo, text=True).strip()
    if changed:
        raise RuntimeError('native source changed: ' + changed)
    files = {}
    paths = sorted((repo / 'src/decision_lab').glob('*.py'))
    paths.append(repo / 'tests/test_research_decision_integration.py')
    for p in paths:
        data = p.read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        rel = p.relative_to(repo).as_posix()
        expected = subprocess.check_output(['git', 'rev-parse', BASE + ':' + rel], cwd=repo, text=True).strip()
        if blob != expected:
            raise RuntimeError('native blob mismatch: ' + rel)
        files[rel] = {'git_blob_sha1': blob, 'sha256': hashlib.sha256(data).hexdigest()}
    rh = hashlib.sha256((ROOT / 'fact_readout.py').read_bytes()).hexdigest()
    assert rh == '9d8227d1fc8b08dd5bd6b5482c9fca5df8f2b02dad16cf3ddd5b703a3bf6b3b1'
    return {'base_commit': BASE, 'production_changed': False, 'reader_sha256': rh,
            'native_files_checked': len(files), 'files': files}


def worker_results(visible):
    data = ''.join(encode(c['request']) + '\n' for c in visible)
    run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'],
                         input=data, text=True, capture_output=True, timeout=900)
    if run.returncode:
        raise RuntimeError(run.stderr)
    answers = [json.loads(line) for line in run.stdout.splitlines()]
    if len(answers) != len(visible):
        raise RuntimeError('worker omitted worlds')
    return answers


def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--verify-repeat', action='store_true')
    args = parser.parse_args()
    if args.worker:
        for line in sys.stdin:
            if line.strip():
                print(encode(native_trace(json.loads(line))), flush=True)
        return
    out = ROOT / 'results'
    out.mkdir(exist_ok=True)
    ident = identity()
    if args.verify_repeat:
        visible = json.loads((out / 'visible_worlds.json').read_text())
        again = worker_results(visible)
        with gzip.open(out / 'native_outputs.json.gz', 'rt') as f:
            original = json.load(f)
        if again != original:
            raise RuntimeError('native deterministic rerun mismatch')
        save(out / 'verification.json', {'status': 'DETERMINISTIC_NATIVE_RERUN_PASS',
             'worlds': len(visible), 'all_native_records_and_readiness_equal': True,
             'native_output_digest': digest(again), 'production_changed': False})
        print('DETERMINISTIC_NATIVE_RERUN_PASS', flush=True)
        return
    visible, oracle = generate()
    freeze = {'protocol_sha256': hashlib.sha256((ROOT / 'PROTOCOL.md').read_bytes()).hexdigest(),
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'reader_sha256': ident['reader_sha256'], 'visible_worlds_hash': digest(visible),
              'oracle_hash': digest(oracle), 'seed': 20260925, 'worlds_per_regime': 32,
              'fixed_K': 3, 'max_B': 6, 'external_preregistration': False}
    save(out / 'pre_run_freeze.json', freeze)
    save(out / 'source_identity.json', ident)
    save(out / 'visible_worlds.json', visible)
    save(out / 'oracle_NOT_SENT_TO_WORKER.json', oracle)
    print('FROZEN; starting 128 native worlds with observed prefixes only.', flush=True)
    answers = worker_results(visible)
    with gzip.open(out / 'native_outputs.json.gz', 'wt') as f:
        json.dump(answers, f, sort_keys=True)
    policy_rows = []
    for case, answer in zip(visible, answers):
        truth = oracle[case['id']]['verdict']
        assert (Fraction(oracle[case['id']]['debt']) <=
                Fraction(oracle[case['id']]['ebitda']) * Fraction(oracle[case['id']]['ceiling'])) == (truth == 'WITHIN_LIMIT')
        for policy, step in choose_steps(answer['trace']).items():
            row = answer['trace'][step]
            verdict = row['readout']['verdict']
            admitted = row['admission'] == 'ADMITTED'
            scored = outcome(verdict, admitted, truth)
            policy_rows.append({'world': case['id'], 'regime': case['regime'], 'policy': policy,
                'queries': step, 'truth': truth, 'verdict': verdict, 'admitted': int(admitted),
                'outcome': scored, 'loss': round(loss(scored, step), 8),
                'action': row['native_route']['action'] if row['native_route'] else 'NO_ADMISSION'})
    with (out / 'policy_rows.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(policy_rows[0]))
        writer.writeheader()
        writer.writerows(policy_rows)
    groups, sensitivity, paired = [], [], []
    for regime in REGIMES:
        regime_rows = [r for r in policy_rows if r['regime'] == regime]
        for policy in ('FIRST_READY', 'FIXED_K', 'MAX_B'):
            rr = [r for r in regime_rows if r['policy'] == policy]
            count = Counter(r['outcome'] for r in rr)
            groups.append({'regime': regime, 'policy': policy, 'n': len(rr),
                'correct': count['CORRECT'], 'wrong': count['WRONG'], 'defer': count['DEFER'],
                'readout_unknown_conflict': sum(r['verdict'] not in RESOLVED for r in rr),
                'no_admission': sum(not r['admitted'] for r in rr),
                'queries_total': sum(r['queries'] for r in rr),
                'mean_queries': sum(r['queries'] for r in rr) / len(rr),
                'mean_loss': sum(r['loss'] for r in rr) / len(rr)})
            for defer in (.1, .25, .5, 1):
                for cost in (0, .01, .02, .05, .1):
                    sensitivity.append({'regime': regime, 'policy': policy, 'defer_penalty': defer,
                                        'query_penalty': cost,
                                        'mean_loss': sum(loss(r['outcome'], r['queries'], defer, cost) for r in rr) / len(rr)})
        transitions = Counter()
        for case in [c for c in visible if c['regime'] == regime]:
            rows = {r['policy']: r for r in regime_rows if r['world'] == case['id']}
            transitions[rows['FIRST_READY']['outcome'] + '->' + rows['MAX_B']['outcome']] += 1
        paired.append({'regime': regime, 'first_ready_to_max': dict(sorted(transitions.items()))})
    save(out / 'sensitivity.json', sensitivity)
    example = next((i for i, c in enumerate(visible) if any(
        r['world'] == c['id'] and r['policy'] == 'FIRST_READY' and r['outcome'] == 'WRONG'
        for r in policy_rows)), 0)
    save(out / 'example.json', {'case': visible[example], 'truth': oracle[visible[example]['id']],
                              'trace': answers[example]['trace']})
    controls = structural_controls({'query': dict(QUERY), 'offers': [
        {'body': disclosure(200, 100, 3, 1), 'family': 'A'},
        {'body': disclosure(200, 100, 3, 2), 'family': 'B'}]})
    summary = {'status': 'E1_NATIVE_SYNTHETIC_MECHANISM_PILOT_COMPLETE', 'worlds': len(visible),
               'archive_snapshots': sum(len(a['trace']) for a in answers),
               'policy_evaluations': len(policy_rows), 'groups': groups, 'paired_transitions': paired,
               'structural_controls': controls, 'pre_run_freeze': freeze,
               'native_output_digest': digest(answers),
               'scope': {'native_workorder_dossier_archive_progression_readiness_admission': True,
                         'native_router': True, 'native_decision_compiler': False,
                         'real_companies': 0, 'LLM_calls': 0, 'OHLCV_classifier': False,
                         'production_modified': False, 'empirical_generalization': False,
                         'default_workorder_policy_semantics_preserved': True},
               'limitations': ['designed synthetic regimes, not population estimates',
                   'fixed G1 latest-revision finite grammar, not optimal evidence integration',
                   'synthetic common background and linkage; not actual financial data',
                   'first eligible source-family independence is an experimental assumption',
                   'execution CLOSED is imposed uniformly at every prefix',
                   'loss units and penalty weights are chosen, not financial facts',
                   'no theorem of optimal stopping; no policy superiority integrity gate']}
    assert len(policy_rows) == 384 and all(controls.values())
    assert all(g['correct'] + g['wrong'] + g['defer'] == 32 for g in groups)
    save(out / 'summary.json', summary)
    print('E1_NATIVE_SYNTHETIC_MECHANISM_PILOT_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
