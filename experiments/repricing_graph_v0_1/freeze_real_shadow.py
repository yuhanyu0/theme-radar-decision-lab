from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .case_io import load_shadow_case
from .context import build_repricing_context
from .gap import calculate_expectation_gap
from .shadow_case import compile_shadow_repricing_decision


ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases"
MARKET_CSV = CASES / "ETN_20260925_market_context.csv"
CASE_YAML = CASES / "ETN_2026Q2_shadow.yaml"
ARTIFACT = CASES / "ETN_20260925_shadow_decision.json"


def _jsonable(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, np.generic):
        return value.item()
    if is_dataclass(value):
        return {key: _jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def build_real_shadow_payload() -> dict[str, object]:
    frame = pd.read_csv(MARKET_CSV, parse_dates=["date"]).set_index("date").sort_index()
    closes = frame[["ETN_close", "NVT_close", "POWL_close"]].rename(
        columns={"ETN_close": "ETN", "NVT_close": "NVT", "POWL_close": "POWL"}
    )
    returns = closes.pct_change()
    ohlcv = frame[["ETN_open", "ETN_high", "ETN_low", "ETN_close", "ETN_volume"]].rename(
        columns={
            "ETN_open": "Open",
            "ETN_high": "High",
            "ETN_low": "Low",
            "ETN_close": "Close",
            "ETN_volume": "Volume",
        }
    )
    benchmark = frame["SPY_close"].rename("SPY")

    case = load_shadow_case(CASE_YAML)
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    context = build_repricing_context(
        returns=returns,
        members=["ETN", "NVT", "POWL"],
        target="ETN",
        ohlcv=ohlcv,
        benchmark_close=benchmark,
        context_as_of=case.as_of,
        market_available_at="2026-09-25T20:05:00+00:00",
        theme_market_observation_ref=None,
        linkage_window=63,
    )
    decision = compile_shadow_repricing_decision(
        case=case,
        gap=gap,
        context=context,
        causal_exposure_validated=True,
        dominant_contradiction=False,
    )
    payload = _jsonable(decision)
    payload["target_excluded_linkage"] = _jsonable(context.target_excluded_linkage)
    payload["market_data_provenance"] = {
        "provider": "Alpaca Market Data",
        "feed": "IEX",
        "timeframe": "1Day",
        "first_session": frame.index.min().date().isoformat(),
        "last_session": frame.index.max().date().isoformat(),
        "symbols": ["ETN", "NVT", "POWL", "SPY"],
        "retrieval_scope": "2026-06-15 through 2026-09-25",
        "note": "Frozen observed daily bars. Not a forward outcome dataset.",
    }
    return payload


def freeze_real_shadow_artifact(path: Path = ARTIFACT) -> dict[str, object]:
    payload = build_real_shadow_payload()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    frozen = freeze_real_shadow_artifact()
    print(json.dumps({
        "case_hash": frozen["case_hash"],
        "status": frozen["status"],
        "gap": frozen["expectation_gap"],
        "tape": frozen["tape_context"],
        "linkage": frozen["target_excluded_linkage"],
    }, indent=2, sort_keys=True))
