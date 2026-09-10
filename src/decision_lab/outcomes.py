from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

DEFAULT_HORIZONS = (1, 3, 5, 10, 20)


@dataclass(frozen=True)
class HorizonOutcome:
    horizon_days: int
    return_: float | None
    benchmark_return: float | None
    theme_relative_return: float | None
    mfe: float | None
    mae: float | None


def _forward_window(series: pd.Series, asof: pd.Timestamp, horizon: int) -> pd.Series:
    future = series.loc[series.index > asof].dropna().head(horizon)
    return future


def evaluate_forward_outcomes(
    *,
    close: pd.Series,
    decision_asof: str | pd.Timestamp,
    benchmark_close: pd.Series | None = None,
    theme_control_close: pd.Series | None = None,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> dict[str, dict | None]:
    """Evaluate immutable forward outcomes without changing the original decision.

    Return/MFE/MAE are measured from the decision-as-of close to subsequent closes.
    The function only reports horizons for which enough future sessions exist.
    """
    close = close.dropna().sort_index()
    asof = pd.Timestamp(decision_asof)
    if close.index.tz is not None and asof.tzinfo is None:
        asof = asof.tz_localize(close.index.tz)
    elif close.index.tz is None and asof.tzinfo is not None:
        asof = asof.tz_convert(None)

    prior = close.loc[close.index <= asof]
    if prior.empty:
        raise ValueError("decision_asof precedes available close history")
    entry = float(prior.iloc[-1])

    benchmark_entry = None
    if benchmark_close is not None:
        b = benchmark_close.dropna().sort_index()
        if b.index.tz is not None and asof.tzinfo is None:
            asof_b = asof.tz_localize(b.index.tz)
        elif b.index.tz is None and asof.tzinfo is not None:
            asof_b = asof.tz_convert(None)
        else:
            asof_b = asof
        b_prior = b.loc[b.index <= asof_b]
        if not b_prior.empty:
            benchmark_entry = float(b_prior.iloc[-1])
    else:
        b = None
        asof_b = asof

    theme_entry = None
    if theme_control_close is not None:
        t = theme_control_close.dropna().sort_index()
        if t.index.tz is not None and asof.tzinfo is None:
            asof_t = asof.tz_localize(t.index.tz)
        elif t.index.tz is None and asof.tzinfo is not None:
            asof_t = asof.tz_convert(None)
        else:
            asof_t = asof
        t_prior = t.loc[t.index <= asof_t]
        if not t_prior.empty:
            theme_entry = float(t_prior.iloc[-1])
    else:
        t = None
        asof_t = asof

    output: dict[str, dict | None] = {}
    for horizon in horizons:
        h = int(horizon)
        future = _forward_window(close, asof, h)
        if len(future) < h:
            output[f"{h}d"] = None
            continue

        path_ret = future / entry - 1.0
        ret = float(path_ret.iloc[-1])
        mfe = float(path_ret.max())
        mae = float(path_ret.min())

        benchmark_ret = None
        if b is not None and benchmark_entry is not None:
            b_future = _forward_window(b, asof_b, h)
            if len(b_future) >= h:
                benchmark_ret = float(b_future.iloc[h - 1] / benchmark_entry - 1.0)

        theme_relative = None
        if t is not None and theme_entry is not None:
            t_future = _forward_window(t, asof_t, h)
            if len(t_future) >= h:
                theme_ret = float(t_future.iloc[h - 1] / theme_entry - 1.0)
                theme_relative = ret - theme_ret
        elif benchmark_ret is not None:
            theme_relative = ret - benchmark_ret

        output[f"{h}d"] = {
            "return": ret,
            "benchmark_return": benchmark_ret,
            "theme_relative_return": theme_relative,
            "mfe": mfe,
            "mae": mae,
        }
    return output


def missed_upside(
    *,
    action: str,
    horizons: dict[str, dict | None],
    reference_horizon: str = "20d",
) -> float | None:
    """Quantify opportunity cost for BLOCKED/WATCH_ONLY decisions.

    This metric is deliberately separate from false-positive rate so a system cannot
    look artificially good merely by refusing to trade.
    """
    if action not in {"BLOCKED", "WATCH_ONLY"}:
        return 0.0
    result = horizons.get(reference_horizon)
    if not result:
        return None
    ret = result.get("theme_relative_return")
    if ret is None:
        ret = result.get("return")
    if ret is None:
        return None
    return float(max(0.0, ret))


def summarize_decisions(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate walk-forward performance by action/playbook/theme/tape stage.

    Expected columns include `forward_return`, `mae`, `mfe`, `action` and grouping
    columns. This helper intentionally does not infer missing outcomes.
    """
    if frame.empty:
        return frame.copy()
    groups = [c for c in ["theme", "playbook", "tape_stage", "action"] if c in frame.columns]
    if not groups:
        raise ValueError("at least one grouping column is required")

    data = frame.copy()
    if "forward_return" not in data:
        raise ValueError("forward_return column is required")
    data["hit"] = data["forward_return"] > 0

    agg = {
        "forward_return": ["count", "mean", "median"],
        "hit": "mean",
    }
    if "mae" in data:
        agg["mae"] = ["mean", "median"]
    if "mfe" in data:
        agg["mfe"] = ["mean", "median"]
    if "missed_upside" in data:
        agg["missed_upside"] = "mean"

    result = data.groupby(groups, dropna=False).agg(agg)
    result.columns = ["_".join(filter(None, map(str, col))).strip("_") for col in result.columns]
    return result.reset_index()
