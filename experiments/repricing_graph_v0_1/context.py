from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from decision_lab.linkage import LinkageResult, leave_one_out_control, rolling_linkage
from decision_lab.tape import TapeAssessment, assess_tape_state


@dataclass(frozen=True)
class RepricingContext:
    theme_market_observation_ref: str | None
    target_excluded_linkage: LinkageResult
    tape_assessment: TapeAssessment
    context_as_of: str
    warnings: tuple[str, ...]


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_repricing_context(
    *,
    returns: pd.DataFrame,
    members: list[str],
    target: str,
    ohlcv: pd.DataFrame,
    benchmark_close: pd.Series | None,
    context_as_of: str,
    market_available_at: str,
    theme_market_observation_ref: str | None,
    linkage_window: int = 63,
) -> RepricingContext:
    if _dt(market_available_at) > _dt(context_as_of):
        raise ValueError("market data available after context_as_of")
    target = target.upper()
    if target not in returns.columns:
        raise ValueError("target return series missing")
    control = leave_one_out_control(returns, members, target)
    linkage = rolling_linkage(
        returns[target],
        control,
        ticker=target,
        control_name=f"DataCenter_Infra_minus_{target}",
        window=linkage_window,
    )
    tape = assess_tape_state(ohlcv, benchmark_close=benchmark_close)
    warnings: list[str] = ["statistical linkage is diagnostic, not causal exposure"]
    if theme_market_observation_ref is None:
        warnings.append("market observation unavailable")
    return RepricingContext(
        theme_market_observation_ref=theme_market_observation_ref,
        target_excluded_linkage=linkage,
        tape_assessment=tape,
        context_as_of=context_as_of,
        warnings=tuple(warnings),
    )
