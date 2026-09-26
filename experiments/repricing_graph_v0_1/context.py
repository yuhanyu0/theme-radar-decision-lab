from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from decision_lab.linkage import LinkageResult, leave_one_out_control, rolling_linkage
from decision_lab.tape import TapeAssessment, assess_tape_state
from decision_lab.themes import ThemePackage

from .case_io import validate_etn_vertical_slice_case
from .model import RepricingCase


@dataclass(frozen=True)
class RepricingContext:
    theme_market_observation_ref: str | None
    target_excluded_linkage: LinkageResult
    tape_assessment: TapeAssessment
    context_as_of: str
    target_excluded_members: tuple[str, ...]
    warnings: tuple[str, ...]


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _validate_market_index(
    index: pd.Index,
    *,
    case_as_of: datetime,
    name: str,
) -> None:
    if len(index) == 0:
        raise ValueError(f"{name} must be non-empty")
    stamps = pd.to_datetime(index)
    latest = stamps.max()
    if getattr(latest, "tzinfo", None) is None:
        latest = latest.tz_localize(UTC)
    else:
        latest = latest.tz_convert(UTC)
    if latest.to_pydatetime() > case_as_of:
        raise ValueError(f"{name} includes data after case as_of")


def build_repricing_context(
    *,
    case: RepricingCase,
    package: ThemePackage,
    returns: pd.DataFrame,
    ohlcv: pd.DataFrame,
    benchmark_close: pd.Series,
    market_available_at: str,
    theme_market_observation_ref: str | None,
    linkage_window: int = 63,
) -> RepricingContext:
    validate_etn_vertical_slice_case(case, package)
    case_dt = _utc(case.as_of)
    if _utc(market_available_at) > case_dt:
        raise ValueError("market available_at exceeds case as_of")
    if case.ticker not in returns.columns:
        raise ValueError("target is missing from return frame")

    _validate_market_index(returns.index, case_as_of=case_dt, name="returns")
    _validate_market_index(ohlcv.index, case_as_of=case_dt, name="ohlcv")
    _validate_market_index(
        benchmark_close.index,
        case_as_of=case_dt,
        name="benchmark_close",
    )

    case_date = case_dt.date().isoformat()
    active = tuple(
        symbol
        for symbol in package.universe.symbols(as_of=case_date)
        if symbol in returns.columns
    )
    control_members = tuple(sorted(symbol for symbol in active if symbol != case.ticker))
    if len(control_members) < 2:
        raise ValueError("target-excluded control requires two available peers")

    control = leave_one_out_control(
        returns,
        list(active),
        case.ticker,
    )
    linkage = rolling_linkage(
        returns[case.ticker],
        control,
        ticker=case.ticker,
        control_name=control.name or f"control_minus_{case.ticker}",
        window=linkage_window,
    )
    tape = assess_tape_state(
        ohlcv,
        benchmark_close=benchmark_close,
    )

    warnings: list[str] = []
    if theme_market_observation_ref is None:
        warnings.append("theme market observation unavailable")
    elif not isinstance(theme_market_observation_ref, str) or not theme_market_observation_ref.strip():
        raise ValueError("theme_market_observation_ref must be non-empty")
    if linkage.circularity_warning:
        warnings.append("target-excluded linkage is statistically near-circular")

    return RepricingContext(
        theme_market_observation_ref=theme_market_observation_ref,
        target_excluded_linkage=linkage,
        tape_assessment=tape,
        context_as_of=case.as_of,
        target_excluded_members=control_members,
        warnings=tuple(warnings),
    )
