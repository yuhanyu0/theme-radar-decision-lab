from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class HierarchicalControlSpec:
    target: str
    market: str
    theme: str
    sector: str | None = None
    industry: str | None = None
    theme_members: tuple[str, ...] = ()

    def validate(self) -> None:
        target = self.target.upper()
        if target in {member.upper() for member in self.theme_members}:
            raise ValueError("target must be excluded from theme control membership")
        names = [name for name in (self.market, self.sector, self.industry, self.theme) if name]
        if len(names) != len(set(names)):
            raise ValueError("hierarchical control names must be unique")

    def ordered_control_names(self) -> tuple[str, ...]:
        return tuple(
            name for name in (self.market, self.sector, self.industry, self.theme) if name
        )


@dataclass(frozen=True)
class HierarchicalLinkageResult:
    target: str
    status: str
    window: int
    observations: int
    theme_correlation: float | None
    theme_beta: float | None
    r2: float | None
    incremental_theme_r2: float | None
    residual_mean: float | None
    residual_vol: float | None
    circularity_warning: bool
    missing_controls: tuple[str, ...]
    coefficients: Mapping[str, float] = field(default_factory=dict)


def _pending(
    spec: HierarchicalControlSpec,
    window: int,
    observations: int,
    missing: tuple[str, ...],
) -> HierarchicalLinkageResult:
    return HierarchicalLinkageResult(
        target=spec.target.upper(),
        status="coverage_pending",
        window=window,
        observations=observations,
        theme_correlation=None,
        theme_beta=None,
        r2=None,
        incremental_theme_r2=None,
        residual_mean=None,
        residual_vol=None,
        circularity_warning=False,
        missing_controls=missing,
        coefficients={},
    )


def _r2(y: np.ndarray, fitted: np.ndarray) -> float | None:
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if ss_tot <= 1e-16:
        return None
    ss_res = float(np.sum((y - fitted) ** 2))
    return float(1.0 - ss_res / ss_tot)


def hierarchical_linkage(
    target_returns: pd.Series,
    controls: Mapping[str, pd.Series],
    spec: HierarchicalControlSpec,
    *,
    window: int = 63,
) -> HierarchicalLinkageResult:
    spec.validate()
    required = spec.ordered_control_names()
    missing = tuple(name for name in required if name not in controls)
    if missing:
        return _pending(spec, window, len(target_returns.tail(window)), missing)

    joined = pd.concat(
        [target_returns.rename("target")]
        + [controls[name].rename(name) for name in required],
        axis=1,
    ).dropna().tail(window)
    n = len(joined)
    if n < max(10, window // 3):
        return _pending(spec, window, n, ())

    target_arr = joined["target"].to_numpy(float)
    for name in required:
        control_arr = joined[name].to_numpy(float)
        if np.allclose(target_arr, control_arr, rtol=1e-7, atol=1e-10):
            raise ValueError(f"identity-like control detected: {name}")

    control_frame = joined[list(required)]
    x_full = np.column_stack([np.ones(n), control_frame.to_numpy(float)])
    coeff = np.linalg.lstsq(x_full, target_arr, rcond=None)[0]
    fitted = x_full @ coeff
    full_r2 = _r2(target_arr, fitted)
    residual = target_arr - fitted

    without_theme = tuple(name for name in required if name != spec.theme)
    x_reduced = np.column_stack(
        [np.ones(n), joined[list(without_theme)].to_numpy(float)]
    )
    reduced_coeff = np.linalg.lstsq(x_reduced, target_arr, rcond=None)[0]
    reduced_r2 = _r2(target_arr, x_reduced @ reduced_coeff)
    incremental = (
        None
        if full_r2 is None or reduced_r2 is None
        else max(0.0, float(full_r2 - reduced_r2))
    )

    coefficients = {
        name: float(value) for name, value in zip(required, coeff[1:], strict=True)
    }
    theme_corr = float(joined["target"].corr(joined[spec.theme]))
    theme_beta = coefficients[spec.theme]
    circularity_warning = bool(
        full_r2 is not None
        and abs(theme_corr) >= 0.995
        and abs(theme_beta - 1.0) <= 0.03
        and full_r2 >= 0.99
    )

    return HierarchicalLinkageResult(
        target=spec.target.upper(),
        status="ok",
        window=window,
        observations=n,
        theme_correlation=theme_corr,
        theme_beta=theme_beta,
        r2=full_r2,
        incremental_theme_r2=incremental,
        residual_mean=float(residual.mean()),
        residual_vol=float(residual.std(ddof=1)),
        circularity_warning=circularity_warning,
        missing_controls=(),
        coefficients=coefficients,
    )
