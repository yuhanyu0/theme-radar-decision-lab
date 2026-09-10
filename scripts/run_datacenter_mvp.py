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

from decision_lab.ledger import canonical_hash, write_immutable_json
from decision_lab.linkage import leave_one_out_control, rolling_linkage
from decision_lab.playbooks import route_playbooks
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


def choose_control_members(universe: ThemeUniverse, ticker: str) -> tuple[str, list[str]]:
    candidate = universe.candidates[ticker]
    same_layer = [c.ticker.upper() for c in universe.by_layer(candidate.layer)]
    # Leave-one-out needs at least two members after removing target.
    if len([x for x in same_layer if x != ticker]) >= 2:
        return f"{universe.theme}:{candidate.layer}:LOO", same_layer
    return f"{universe.theme}:composite:LOO", universe.symbols()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", default="config/datacenter_seed.example.yaml", type=Path
    )
    parser.add_argument("--period", default="2y")
    parser.add_argument("--theme-key", action="store_true")
    parser.add_argument("--world-confidence", default="unknown")
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

    generated_at = datetime.now(timezone.utc)
    market_asof = max(frame.index.max() for frame in frames.values()).isoformat()
    rows = []

    for ticker in universe.symbols():
        if ticker not in frames or ticker not in returns.columns:
            continue
        control_name, control_members = choose_control_members(universe, ticker)
        available_members = [s for s in control_members if s in returns.columns]
        try:
            control = leave_one_out_control(returns, available_members, ticker)
            linkage = rolling_linkage(
                returns[ticker],
                control,
                ticker=ticker,
                control_name=control_name,
                window=63,
            )
        except ValueError as exc:
            linkage = None
            linkage_error = str(exc)
        else:
            linkage_error = None

        benchmark = frames.get("SPY", pd.DataFrame()).get("Close")
        tape = assess_tape_state(
            frames[ticker], benchmark_close=benchmark, lookback=60
        )
        routing = route_playbooks(
            theme_key=args.theme_key,
            tape_state=tape.state,
            tape_stage=tape.stage,
            fundamentals_intact=False,  # independent fundamentals adapter comes in v0.2
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
            "linkage": None if linkage is None else asdict(linkage),
            "linkage_error": linkage_error,
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

    report = {
        "generated_at": generated_at.isoformat(),
        "market_asof": market_asof,
        "theme": universe.theme,
        "universe_version": universe.version,
        "theme_key_input": bool(args.theme_key),
        "world_confidence_input": args.world_confidence,
        "missing_market_data": missing,
        "source_notes": [
            "Market OHLCV is independently downloaded with yfinance auto_adjust=True.",
            "Radar/Navigator is intentionally not ingested in this public-safe MVP.",
            "Playbook scores are match scores, not calibrated probabilities.",
            "Fundamentals are not yet assumed intact; primary-source evidence adapter is v0.2.",
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
                "theme_state": "independent_market_only_mvp",
                "theme_key": bool(args.theme_key),
                "dynamic_universe_layer": row["layer"],
                "company_state": "not_yet_primary_source_validated",
                "linkage": row["linkage"] or {},
                "tape": row["tape"],
                "playbooks": {
                    "scores": row["playbooks"]["normalized_scores"],
                    "selected": row["playbooks"]["selected"],
                    "probability_is_calibrated": False,
                    "sample_size": None,
                },
                "action": row["playbooks"]["action"],
                "strongest_reason_not_to_trade": "primary-source company validation not yet wired",
                "evidence_refs": [report["report_hash"]],
                "source_timestamps": {"market": market_asof, "radar": None},
                "model_version": "decision-lab-v0.1",
                "config_hash": canonical_hash(args.config.read_text(encoding="utf-8")),
            }
            write_immutable_json(ledger_root / f"{row['ticker']}.json", decision)


if __name__ == "__main__":
    main()
