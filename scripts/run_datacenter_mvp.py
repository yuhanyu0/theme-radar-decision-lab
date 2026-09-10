#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml
import yfinance as yf

from decision_lab.controls import build_layered_leave_one_out_controls
from decision_lab.ledger import canonical_hash, write_immutable_json
from decision_lab.linkage import rolling_linkage
from decision_lab.playbooks import route_playbooks
from decision_lab.radar import GitHubRadarClient
from decision_lab.tape import assess_tape_state
from decision_lab.universe import ThemeUniverse


def load_universe(path: Path) -> ThemeUniverse:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ThemeUniverse.from_records(
        theme=cfg["theme"],
        layers=cfg["layers"],
        candidates=cfg["candidates"],
        version=str(cfg.get("version", "0.1")),
    )


def download(symbols: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        data = yf.download(
            symbol,
            period=period,
            interval="1d",
            auto_adjust=True,
            progress=False,
            actions=False,
            threads=False,
        )
        if data.empty:
            continue
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        frames[symbol] = data[["Open", "High", "Low", "Close", "Volume"]].dropna()
    return frames


def price_returns(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    series = {
        symbol: frame["Close"].pct_change().rename(symbol)
        for symbol, frame in frames.items()
        if len(frame) >= 25
    }
    return pd.concat(series.values(), axis=1).sort_index() if series else pd.DataFrame()


def maybe_fetch_radar(signal_date: str | None) -> dict | None:
    if not signal_date:
        return None
    snapshot = GitHubRadarClient().fetch_daily(signal_date)
    return {
        "signal_date": snapshot.signal_date,
        "leaders_v1": snapshot.leaders_v1,
        "challengers_v2": snapshot.challengers_v2,
        "challengers_v3": snapshot.challengers_v3,
        "migration_risers": snapshot.migration_risers,
        "migration_fallers": snapshot.migration_fallers,
        "risk_line": snapshot.risk_line,
        "risk_percentiles": snapshot.risk_percentiles,
        "regime": snapshot.regime,
        "bundle_root_sha256": snapshot.bundle_root_sha256,
        "source_ref": snapshot.source_ref,
        "source_blob_sha": snapshot.source_blob_sha,
        "source_commit_sha": snapshot.source_commit_sha,
        "snapshot_hash": snapshot.snapshot_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/datacenter_seed.example.yaml", type=Path)
    parser.add_argument("--period", default="2y")
    parser.add_argument("--theme-key", action="store_true")
    parser.add_argument("--world-confidence", default="unknown")
    parser.add_argument("--radar-date", default=None)
    parser.add_argument("--output-dir", default="artifacts", type=Path)
    parser.add_argument("--write-ledger", action="store_true")
    args = parser.parse_args()

    universe = load_universe(args.config)
    symbols = sorted(set(universe.symbols() + ["SPY"]))
    frames = download(symbols, args.period)
    missing = sorted(set(symbols).difference(frames))
    returns = price_returns(frames)
    if returns.empty:
        raise SystemExit("No market data downloaded")

    radar = maybe_fetch_radar(args.radar_date)
    generated_at = datetime.now(timezone.utc)
    market_asof = max(frame.index.max() for frame in frames.values()).isoformat()
    rows = []

    for ticker in universe.symbols():
        if ticker not in frames or ticker not in returns.columns:
            continue

        controls_error = None
        controls_warnings: list[str] = []
        composite_linkage = None
        layer_linkage = None
        try:
            controls = build_layered_leave_one_out_controls(returns, universe, ticker)
            controls_warnings = list(controls.warnings)
            composite_linkage = rolling_linkage(
                returns[ticker],
                controls.composite_control,
                ticker=ticker,
                control_name=controls.composite_control_name,
                window=63,
            )
            if controls.layer_control is not None and controls.layer_control_name is not None:
                layer_linkage = rolling_linkage(
                    returns[ticker],
                    controls.layer_control,
                    ticker=ticker,
                    control_name=controls.layer_control_name,
                    window=63,
                )
        except ValueError as exc:
            controls_error = str(exc)

        benchmark = frames.get("SPY", pd.DataFrame()).get("Close")
        tape = assess_tape_state(frames[ticker], benchmark_close=benchmark, lookback=60)
        routing = route_playbooks(
            theme_key=args.theme_key,
            tape_state=tape.state,
            tape_stage=tape.stage,
            fundamentals_intact=False,  # primary-source company adapter comes next
            world_confidence=args.world_confidence,
        )

        candidate = universe.candidates[ticker]
        row = {
            "ticker": ticker,
            "theme": universe.theme,
            "layer": candidate.layer,
            "membership_state": candidate.membership_state,
            "seed_expression_role": candidate.expression_role,
            "market_asof": market_asof,
            "linkage_composite": None if composite_linkage is None else asdict(composite_linkage),
            "linkage_layer": None if layer_linkage is None else asdict(layer_linkage),
            "control_warnings": controls_warnings,
            "controls_error": controls_error,
            "tape": asdict(tape),
            "playbooks": {
                "raw_scores": dict(routing.raw_scores),
                "normalized_scores": dict(routing.normalized_scores),
                "selected": routing.selected_playbook,
                "action": routing.action,
                "probability_is_calibrated": routing.probability_is_calibrated,
                "rationale": list(routing.rationale),
            },
        }
        rows.append(row)

    datacenter_migration = None
    if radar is not None:
        datacenter_migration = radar["migration_risers"].get("DataCenter_Infra")
        if datacenter_migration is None:
            datacenter_migration = radar["migration_fallers"].get("DataCenter_Infra")

    report = {
        "generated_at": generated_at.isoformat(),
        "market_asof": market_asof,
        "theme": universe.theme,
        "universe_version": universe.version,
        "theme_key_input": bool(args.theme_key),
        "world_confidence_input": args.world_confidence,
        "radar_model_evidence": radar,
        "radar_datacenter_migration": datacenter_migration,
        "missing_market_data": missing,
        "source_notes": [
            "Market OHLCV is independently downloaded with yfinance auto_adjust=True.",
            "Theme controls are layer-equal and leave-one-out; target is excluded everywhere.",
            "Radar is optional model-output evidence and never defines ground truth.",
            "Navigator structure/carry is not available from Radar daily markdown and is not fabricated.",
            "Playbook scores are match scores, not calibrated probabilities.",
            "Fundamentals are not assumed intact until primary-source company evidence is wired.",
        ],
        "candidates": rows,
    }
    report["report_hash"] = canonical_hash(report)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    report_path = args.output_dir / f"datacenter_mvp_{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {report_path}")

    if args.write_ledger:
        if os.environ.get("ALLOW_LIVE_LEDGER", "").lower() not in {"1", "true", "yes"}:
            raise SystemExit(
                "Refusing live ledger write: set ALLOW_LIVE_LEDGER=true only after privacy review"
            )
        ledger_root = Path("ledger/live") / generated_at.strftime("%Y/%m/%d")
        for row in rows:
            decision = {
                "decision_id": f"{stamp}-{universe.theme}-{row['ticker']}",
                "created_at": generated_at.isoformat(),
                "market_asof": market_asof,
                "theme": universe.theme,
                "ticker": row["ticker"],
                "radar_run_id": None,
                "radar_source_commit": None if radar is None else radar["source_commit_sha"],
                "theme_state": "market_and_radar_mvp" if radar else "independent_market_only_mvp",
                "theme_key": bool(args.theme_key),
                "dynamic_universe_layer": row["layer"],
                "company_state": "not_yet_primary_source_validated",
                "linkage": row["linkage_composite"] or {},
                "tape": row["tape"],
                "playbooks": {
                    "scores": row["playbooks"]["normalized_scores"],
                    "selected": row["playbooks"]["selected"],
                    "probability_is_calibrated": False,
                    "sample_size": None,
                },
                "action": row["playbooks"]["action"],
                "strongest_reason_not_to_trade": "primary-source company validation not yet wired",
                "evidence_refs": [report["report_hash"]]
                + ([] if radar is None else [radar["snapshot_hash"]]),
                "source_timestamps": {
                    "market": market_asof,
                    "radar": None if radar is None else radar["signal_date"],
                },
                "model_version": "decision-lab-v0.1",
                "config_hash": canonical_hash(args.config.read_text(encoding="utf-8")),
            }
            write_immutable_json(ledger_root / f"{row['ticker']}.json", decision)


if __name__ == "__main__":
    main()
