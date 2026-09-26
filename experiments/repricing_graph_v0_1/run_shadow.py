"""Compile a source-bound research snapshot offline. No broker or runtime network.

The real case intentionally has no independent earnings forecast. The runner
must preserve that absence rather than derive a bullish prediction from Tape.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import pandas as pd

from decision_lab.ledger import canonical_hash
from decision_lab.linkage import leave_one_out_control
from decision_lab.themes import load_theme_package

from .case_io import load_shadow_case, validate_etn_vertical_slice_case
from .context import build_repricing_context
from .evaluate import Ablation, evaluate_shadow_case, run_ablation
from .gap import calculate_expectation_gap
from .shadow_case import compile_shadow_repricing_decision, json_values
from .template import load_etn_template

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent


def read_market(directory: Path) -> tuple[dict[str, pd.DataFrame], dict]:
    receipt = json.loads((directory / 'receipt.json').read_text())
    frames = {}
    for symbol, meta in receipt['symbols'].items():
        if meta['status'] != 'FETCHED':
            raise ValueError('market input unavailable: ' + symbol)
        if symbol not in {'ETN', 'POWL', 'NVT', 'SPY', 'XLI'}:
            raise ValueError('unexpected market symbol')
        path = directory / (symbol + '.csv')
        if hashlib.sha256(path.read_bytes()).hexdigest() != meta['sha256']:
            raise ValueError('market input hash mismatch: ' + symbol)
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frames[symbol] = frame
    if set(frames) != {'ETN', 'POWL', 'NVT', 'SPY', 'XLI'}:
        raise ValueError('required market symbols missing')
    return frames, receipt


def build_report(case_path: Path, template_path: Path, market_dir: Path) -> dict:
    case = load_shadow_case(case_path)
    package = load_theme_package(ROOT / 'config/themes/datacenter_infra.yaml')
    validate_etn_vertical_slice_case(case, package)
    graph = load_etn_template(template_path)
    frames, receipt = read_market(market_dir)
    prices = pd.concat({s: frame['Close'] for s, frame in frames.items()}, axis=1)
    if prices.isna().any().any():
        raise ValueError('market session coverage differs between symbols')
    members = [c.ticker for c in package.universe.by_layer(
        'electrical_switchgear', as_of=case.as_of[:10])]
    if set(members) != {'ETN', 'POWL', 'NVT'}:
        raise ValueError('frozen layer membership changed; review before rerun')
    returns = prices.pct_change(fill_method=None).dropna()
    exposure_refs = tuple(s.source_id for s in case.sources
                          if s.source_id == 'etn_q2_primary_capture')
    context = build_repricing_context(
        target='ETN', members=members, returns=returns,
        ohlcv=frames['ETN'], benchmark_close=prices['SPY'], as_of=case.as_of,
        market_data_available_at=receipt['retrieved_at'], market_observation_ref=None,
        economic_exposure_evidence_refs=exposure_refs,
    )
    gap = (calculate_expectation_gap(case.our_expectation, case.market_expectation)
           if case.our_expectation is not None and case.market_expectation is not None
           else None)
    decision = compile_shadow_repricing_decision(
        case=case, gap=gap, context=context, graph=graph,
    )
    control = leave_one_out_control(returns, members, 'ETN')
    control_level = pd.concat([pd.Series([1.0], index=prices.index[:1]),
                               (1 + control).cumprod()]).reindex(prices.index)
    outcome = evaluate_shadow_case(decision=decision, close=prices['ETN'],
        spy_close=prices['SPY'], sector_close=prices['XLI'], theme_control_close=control_level)
    source_payloads = {s.source_id: json.loads(s.payload_json) for s in case.sources}
    guidance = source_payloads['etn_q2_primary_capture']['value']
    indexed = source_payloads['barchart_indexed_reference']['value']
    diagnostic = {
        'label': 'guidance_vs_indexed_estimate_only_NOT_our_forecast_or_alpha',
        'unit': 'USD/share', 'low': float(Decimal(str(guidance['adjusted_eps_low'])) - Decimal(str(indexed))),
        'high': float(Decimal(str(guidance['adjusted_eps_high'])) - Decimal(str(indexed))),
        'upstream_consensus_vintage_verified': False,
        'eps_definition_reconciled': False,
        'used_for_candidate_promotion': False,
    }
    report = {
        'status': 'SOURCE_CAPTURE_COMPLETE_RESEARCHING_MODEL_INPUTS_MISSING',
        'decision': asdict(decision), 'context': asdict(context),
        'sources': list(source_payloads.values()), 'market_receipt': receipt,
        'guidance_vs_indexed_estimate_diagnostic': diagnostic,
        'our_independent_eps_estimate': None if case.our_expectation is None else asdict(case.our_expectation),
        'expected_stock_return': None,
        'outcomes': asdict(outcome),
        'ablation_metadata_only': [asdict(run_ablation(decision, a)) for a in Ablation],
        'scope': {
            'orders_placed': False, 'capital_sized': False,
            'full_theme_market_observation': 'unavailable; same-layer peers are not substituted for whole theme',
            'control_members': list(context.control_members),
            'price_basis': 'current-vintage raw Close for linkage and native close-to-close diagnostics; not net trading returns',
            'membership_scope': 'current-case electrical_switchgear membership only; no historical membership alpha test',
            'causal_exposure_flag': 'presence of referenced qualitative exposure evidence, not a measured elasticity',
            'outcome_scope': '20/60 subsequent sessions unavailable at snapshot; no P&L claim',
            'ablation_scope': 'input-removal declarations only; no ablation performance experiment',
        },
    }
    report = json_values(report)
    report['report_hash'] = canonical_hash(report)
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', type=Path, default=BASE / 'cases/ETN_20260926_capture.yaml')
    p.add_argument('--graph', type=Path, default=BASE / 'datacenter_etn_template.yaml')
    p.add_argument('--market-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    report = build_report(args.case, args.graph, args.market_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, allow_nan=False)
    print('STATUS:', report['status'])
    print('DECISION:', report['decision']['status'])
    print('REPORT HASH:', report['report_hash'])


if __name__ == '__main__':
    main()
