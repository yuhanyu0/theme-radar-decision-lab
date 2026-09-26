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
    control_members: tuple[str, ...]
    causal_exposure_validated: bool
    warnings: tuple[str, ...]


def _time(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return dt


def build_repricing_context(
    *,
    target: str,
    members: list[str],
    returns: pd.DataFrame,
    ohlcv: pd.DataFrame,
    benchmark_close: pd.Series,
    as_of: str,
    market_data_available_at: str,
    market_observation_ref: str | None,
    economic_exposure_evidence_refs: tuple[str, ...],
    linkage_window: int = 63,
) -> RepricingContext:
    target = target.upper()
    if _time(market_data_available_at) > _time(as_of):
        raise ValueError("market data available after context as_of")
    control_members = tuple(
        ticker.upper()
        for ticker in members
        if ticker.upper() != target and ticker.upper() in returns.columns
    )
    control = leave_one_out_control(
        returns,
        members,
        target,
    )
    if target not in returns.columns:
        raise ValueError("target returns are unavailable")
    linkage = rolling_linkage(
        returns[target],
        control,
        ticker=target,
        control_name=f"theme_control_minus_{target}",
        window=linkage_window,
    )
    tape = assess_tape_state(
        ohlcv,
        benchmark_close=benchmark_close,
    )

    warnings: list[str] = []
    if market_observation_ref is None:
        warnings.append("market observation unavailable")
    causal_exposure_validated = bool(economic_exposure_evidence_refs)
    if not causal_exposure_validated:
        warnings.append("economic exposure evidence missing")

    return RepricingContext(
        theme_market_observation_ref=market_observation_ref,
        target_excluded_linkage=linkage,
        tape_assessment=tape,
        context_as_of=as_of,
        control_members=control_members,
        causal_exposure_validated=causal_exposure_validated,
        warnings=tuple(warnings),
    )
