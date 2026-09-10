from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LinkageResult:
    ticker: str
    control_name: str
    window: int
    correlation: float | None
    beta: float | None
    r2: float | None
    residual_mean: float | None
    residual_vol: float | None
    beta_stability: float | None
    decoupling_score: float | None
    circularity_warning: bool
    observations: int


def leave_one_out_control(
    returns: pd.DataFrame,
    members: list[str],
    target: str,
    *,
    weights: dict[str, float] | None = None,
) -> pd.Series:
    """Build a theme control that mechanically excludes the target ticker.

    The default is equal-weight. If explicit weights are provided, they are
    renormalized after the target is removed.
    """
    target = target.upper()
    available = [m.upper() for m in members if m.upper() in returns.columns and m.upper() != target]
    if len(available) < 2:
        raise ValueError("leave-one-out control requires at least two non-target members")

    frame = returns[available].dropna(how="all")
    if weights is None:
        return frame.mean(axis=1, skipna=True).rename(f"control_minus_{target}")

    raw = pd.Series({m: float(weights.get(m, 0.0)) for m in available})
    if raw.abs().sum() == 0:
        raise ValueError("provided control weights sum to zero after target exclusion")
    normalized = raw / raw.sum()
    return frame.mul(normalized, axis=1).sum(axis=1, min_count=1).rename(
        f"control_minus_{target}"
    )


def _ols_metrics(y: pd.Series, x: pd.Series) -> tuple[float, float, float, float, int]:
    joined = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    n = len(joined)
    if n < 10 or joined["x"].var(ddof=1) <= 1e-16:
        return np.nan, np.nan, np.nan, np.nan, n

    x_arr = joined["x"].to_numpy(float)
    y_arr = joined["y"].to_numpy(float)
    X = np.column_stack([np.ones(n), x_arr])
    alpha, beta = np.linalg.lstsq(X, y_arr, rcond=None)[0]
    fitted = alpha + beta * x_arr
    residual = y_arr - fitted
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((y_arr - y_arr.mean()) ** 2))
    r2 = np.nan if ss_tot <= 1e-16 else 1.0 - ss_res / ss_tot
    return float(beta), float(r2), float(residual.mean()), float(residual.std(ddof=1)), n


def _rolling_beta(y: pd.Series, x: pd.Series, window: int) -> pd.Series:
    joined = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    cov = joined["y"].rolling(window).cov(joined["x"])
    var = joined["x"].rolling(window).var()
    return cov / var.replace(0.0, np.nan)


def rolling_linkage(
    ticker_returns: pd.Series,
    control_returns: pd.Series,
    *,
    ticker: str,
    control_name: str,
    window: int = 63,
) -> LinkageResult:
    """Estimate current ticker-to-theme linkage with anti-circularity diagnostics.

    `beta_stability` is 1 - coefficient of variation of rolling beta, clipped to [0, 1].
    `decoupling_score` increases as absolute correlation falls and residual volatility
    rises relative to ticker volatility. These are diagnostics, not trading signals.
    """
    joined = pd.concat(
        [ticker_returns.rename("ticker"), control_returns.rename("control")], axis=1
    ).dropna()
    tail = joined.tail(window)
    n = len(tail)
    if n < max(10, window // 3):
        return LinkageResult(
            ticker=ticker,
            control_name=control_name,
            window=window,
            correlation=None,
            beta=None,
            r2=None,
            residual_mean=None,
            residual_vol=None,
            beta_stability=None,
            decoupling_score=None,
            circularity_warning=False,
            observations=n,
        )

    correlation = float(tail["ticker"].corr(tail["control"]))
    beta, r2, residual_mean, residual_vol, _ = _ols_metrics(
        tail["ticker"], tail["control"]
    )

    beta_series = _rolling_beta(joined["ticker"], joined["control"], window).dropna().tail(window)
    if len(beta_series) >= 5 and abs(beta_series.mean()) > 1e-12:
        cv = float(beta_series.std(ddof=1) / abs(beta_series.mean()))
        beta_stability = float(np.clip(1.0 - cv, 0.0, 1.0))
    else:
        beta_stability = None

    ticker_vol = float(tail["ticker"].std(ddof=1))
    residual_ratio = (
        0.0
        if ticker_vol <= 1e-16 or not np.isfinite(residual_vol)
        else float(np.clip(residual_vol / ticker_vol, 0.0, 2.0) / 2.0)
    )
    decoupling_score = float(
        np.clip(0.6 * (1.0 - abs(correlation)) + 0.4 * residual_ratio, 0.0, 1.0)
    )

    circularity_warning = bool(
        np.isfinite(correlation)
        and np.isfinite(beta)
        and np.isfinite(r2)
        and abs(correlation) >= 0.995
        and abs(beta - 1.0) <= 0.03
        and r2 >= 0.99
    )

    return LinkageResult(
        ticker=ticker,
        control_name=control_name,
        window=window,
        correlation=correlation,
        beta=None if not np.isfinite(beta) else beta,
        r2=None if not np.isfinite(r2) else r2,
        residual_mean=None if not np.isfinite(residual_mean) else residual_mean,
        residual_vol=None if not np.isfinite(residual_vol) else residual_vol,
        beta_stability=beta_stability,
        decoupling_score=decoupling_score,
        circularity_warning=circularity_warning,
        observations=n,
    )
