from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TAPE_STATES = {
    "falling_knife",
    "failed_rebound",
    "attempted_base",
    "higher_low",
    "reclaim",
    "clean_retest",
    "breakout",
    "squeeze",
    "extended",
    "range",
    "transition",
}


@dataclass(frozen=True)
class TapeAssessment:
    state: str
    stage: str
    support: float | None
    reclaim: float | None
    pivot: float | None
    invalidation: float | None
    higher_low: bool
    new_low_recently: bool
    volume_confirmation: bool
    volatility_contraction: bool
    relative_strength_positive: bool | None
    reasons: tuple[str, ...]


def _atr(frame: pd.DataFrame, window: int = 14) -> pd.Series:
    prev_close = frame["Close"].shift(1)
    tr = pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - prev_close).abs(),
            (frame["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window).mean()


def _recent_swing_lows(low: pd.Series, order: int = 2) -> list[tuple[pd.Timestamp, float]]:
    points: list[tuple[pd.Timestamp, float]] = []
    values = low.to_numpy(float)
    for i in range(order, len(values) - order):
        center = values[i]
        if np.isfinite(center) and center <= np.nanmin(values[i - order : i + order + 1]):
            points.append((low.index[i], float(center)))
    return points


def assess_tape_state(
    ohlcv: pd.DataFrame,
    *,
    benchmark_close: pd.Series | None = None,
    reclaim_level: float | None = None,
    support_level: float | None = None,
    lookback: int = 60,
) -> TapeAssessment:
    """Classify price *path*, not just a point-in-time indicator.

    The implementation is deliberately conservative. It is intended as a router input,
    not an autonomous trade signal. Explicit externally researched support/reclaim levels
    can be supplied; otherwise recent *prior* swing structure is used so the current bar
    cannot mechanically define the level that it is supposed to reclaim.
    """
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = set(required).difference(ohlcv.columns)
    if missing:
        raise ValueError(f"missing OHLCV columns: {sorted(missing)}")

    frame = ohlcv[required].dropna().tail(max(lookback, 25)).copy()
    if len(frame) < 20:
        raise ValueError("at least 20 valid bars are required")

    close = frame["Close"]
    low = frame["Low"]
    high = frame["High"]
    volume = frame["Volume"]
    atr = _atr(frame).iloc[-1]
    if not np.isfinite(atr) or atr <= 0:
        atr = float(close.tail(20).std(ddof=1))

    last_close = float(close.iloc[-1])
    rolling_low_20 = low.rolling(20).min()
    new_low_recently = bool((low.tail(3) <= rolling_low_20.tail(3) * 1.001).any())

    ma5 = float(close.rolling(5).mean().iloc[-1])
    ma10 = float(close.rolling(10).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    slope10 = float(close.tail(10).pct_change().dropna().mean())

    vol20 = close.pct_change().rolling(20).std()
    vol5 = close.pct_change().rolling(5).std()
    volatility_contraction = bool(
        np.isfinite(vol20.iloc[-1])
        and np.isfinite(vol5.iloc[-1])
        and vol5.iloc[-1] < vol20.iloc[-1] * 0.8
    )

    volume20 = float(volume.rolling(20).mean().iloc[-1])
    volume_confirmation = bool(volume.iloc[-1] >= volume20 * 1.2) if volume20 > 0 else False

    swings = _recent_swing_lows(low.tail(45), order=2)
    higher_low = False
    inferred_support = None
    if len(swings) >= 2:
        (_, prior_low), (_, recent_low) = swings[-2], swings[-1]
        tolerance = 0.20 * atr if np.isfinite(atr) else 0.0
        higher_low = recent_low > prior_low + tolerance
        inferred_support = recent_low
    elif len(swings) == 1:
        inferred_support = swings[-1][1]

    support = float(support_level) if support_level is not None else inferred_support
    if support is None:
        support = float(low.iloc[-20:-1].min())

    # Prior-only levels: exclude the latest bar (and for the retest anchor exclude
    # the latest two bars) to prevent a circular "reclaim of today's own high".
    prior_highs = high.iloc[-21:-1] if len(high) >= 21 else high.iloc[:-1]
    prior_closes_for_reclaim = close.iloc[-12:-2] if len(close) >= 12 else close.iloc[:-2]
    inferred_pivot = float(prior_highs.max())
    inferred_reclaim = float(prior_closes_for_reclaim.max())
    reclaim = float(reclaim_level) if reclaim_level is not None else inferred_reclaim
    pivot = max(reclaim, inferred_pivot)
    invalidation = support - (0.5 * atr if np.isfinite(atr) else 0.0)

    relative_strength_positive: bool | None = None
    if benchmark_close is not None:
        bench = benchmark_close.reindex(close.index).ffill().dropna()
        aligned = pd.concat([close.rename("asset"), bench.rename("bench")], axis=1).dropna()
        if len(aligned) >= 20:
            asset_ret = aligned["asset"].iloc[-1] / aligned["asset"].iloc[-20] - 1.0
            bench_ret = aligned["bench"].iloc[-1] / aligned["bench"].iloc[-20] - 1.0
            relative_strength_positive = bool(asset_ret > bench_ret)

    reasons: list[str] = []

    if new_low_recently and slope10 < 0 and last_close < ma10:
        state = "falling_knife"
        stage = "B0"
        reasons.append("recent lower-low behavior with negative short trend")
    elif last_close < support and ma5 < ma10 < ma20:
        state = "failed_rebound"
        stage = "B0"
        reasons.append("support failed while short moving averages remain bearish")
    else:
        no_new_5d_low = float(low.tail(5).min()) > float(low.iloc[-20:-5].min()) * 0.995
        range5 = float((high.tail(5).max() - low.tail(5).min()) / max(last_close, 1e-12))
        range20 = float((high.tail(20).max() - low.tail(20).min()) / max(last_close, 1e-12))
        attempted_base = no_new_5d_low and range5 < range20 * 0.55

        crossed_reclaim_now = bool(last_close > reclaim and float(close.iloc[-2]) <= reclaim)
        had_prior_reclaim = bool((close.iloc[-5:-1] > reclaim).any())
        held_above_reclaim = bool((close.tail(2) >= reclaim * 0.995).all())
        retest_near_reclaim = bool(
            float(low.tail(2).min()) <= reclaim + 0.35 * atr
            and float(low.tail(2).min()) >= reclaim - 0.50 * atr
        )
        breakout = bool(last_close > inferred_pivot and volume_confirmation)
        extended = bool(last_close > ma20 + 2.5 * atr)
        squeeze = bool(volatility_contraction and range5 < range20 * 0.40)

        if had_prior_reclaim and held_above_reclaim and retest_near_reclaim and higher_low:
            state = "clean_retest"
            stage = "B3"
            reasons.extend(["prior reclaim held on retest", "higher low present"])
        elif crossed_reclaim_now and higher_low:
            state = "reclaim"
            stage = "B2"
            reasons.extend(["prior key level reclaimed", "higher low present"])
        elif higher_low:
            state = "higher_low"
            stage = "B2"
            reasons.append("latest swing low is above prior swing low")
        elif attempted_base:
            state = "attempted_base"
            stage = "B1"
            reasons.append("range contracted without a fresh low")
        elif breakout:
            state = "breakout"
            stage = "A1"
            reasons.append("prior-range breakout with volume confirmation")
        elif squeeze:
            state = "squeeze"
            stage = "D1"
            reasons.append("short volatility/range compression")
        elif extended:
            state = "extended"
            stage = "F_watch"
            reasons.append("price is materially extended above medium trend")
        elif abs(last_close / ma20 - 1.0) < 0.03:
            state = "range"
            stage = "neutral"
            reasons.append("price is close to medium trend without a stronger path signal")
        else:
            state = "transition"
            stage = "neutral"
            reasons.append("path does not yet qualify for a higher-confidence state")

    if volatility_contraction:
        reasons.append("realized volatility is contracting")
    if volume_confirmation:
        reasons.append("latest volume is above recent average")
    if relative_strength_positive is True:
        reasons.append("20-session relative strength exceeds benchmark")
    elif relative_strength_positive is False:
        reasons.append("20-session relative strength trails benchmark")

    return TapeAssessment(
        state=state,
        stage=stage,
        support=float(support),
        reclaim=float(reclaim),
        pivot=float(pivot),
        invalidation=float(invalidation),
        higher_low=higher_low,
        new_low_recently=new_low_recently,
        volume_confirmation=volume_confirmation,
        volatility_contraction=volatility_contraction,
        relative_strength_positive=relative_strength_positive,
        reasons=tuple(reasons),
    )
