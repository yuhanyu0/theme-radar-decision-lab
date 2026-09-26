from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from decision_lab.outcomes import evaluate_forward_outcomes

from .shadow_case import ShadowRepricingDecision


class Ablation(str, Enum):
    FULL = "FULL"
    NO_ECONOMIC_EXPOSURE_VALIDATION = "NO_ECONOMIC_EXPOSURE_VALIDATION"
    NO_MARKET_EXPECTATION_GAP = "NO_MARKET_EXPECTATION_GAP"
    NO_CATALYST_REQUIREMENT = "NO_CATALYST_REQUIREMENT"
    NO_TAPE_CONTEXT = "NO_TAPE_CONTEXT"
    NO_TARGET_EXCLUDED_CONTROL = "NO_TARGET_EXCLUDED_CONTROL"


@dataclass(frozen=True)
class ShadowOutcomeRecord:
    source_case_hash: str
    decision_asof: str
    evaluated_through: str
    spy_horizons: dict[str, dict | None]
    sector_horizons: dict[str, dict | None] | None
    theme_control_horizons: dict[str, dict | None] | None
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class AblationRecord:
    source_case_hash: str
    ablation: Ablation
    removed_component: str | None
    mechanism_claim_allowed: bool
    kill_if_no_degradation: bool
    provenance: tuple[str, ...]


_REMOVED = {
    Ablation.FULL: None,
    Ablation.NO_ECONOMIC_EXPOSURE_VALIDATION: "economic_exposure_validation",
    Ablation.NO_MARKET_EXPECTATION_GAP: "market_expectation_gap",
    Ablation.NO_CATALYST_REQUIREMENT: "catalyst_requirement",
    Ablation.NO_TAPE_CONTEXT: "tape_context",
    Ablation.NO_TARGET_EXCLUDED_CONTROL: "target_excluded_control",
}


def _evaluate(
    *,
    close: pd.Series,
    decision_asof: str,
    benchmark_close: pd.Series | None = None,
    theme_control_close: pd.Series | None = None,
) -> dict[str, dict | None]:
    return evaluate_forward_outcomes(
        close=close,
        decision_asof=decision_asof,
        benchmark_close=benchmark_close,
        theme_control_close=theme_control_close,
        horizons=(20, 60),
    )


def _require_complete(horizons: dict[str, dict | None], *, label: str) -> None:
    missing = [name for name in ("20d", "60d") if horizons.get(name) is None]
    if missing:
        raise ValueError(
            f"insufficient future sessions for {label}: {', '.join(missing)}"
        )


def evaluate_shadow_case(
    *,
    decision: ShadowRepricingDecision,
    close: pd.Series,
    spy_close: pd.Series,
    sector_close: pd.Series | None = None,
    theme_control_close: pd.Series | None = None,
) -> ShadowOutcomeRecord:
    if close.empty:
        raise ValueError("close series must be non-empty")

    spy = _evaluate(
        close=close,
        decision_asof=decision.as_of,
        benchmark_close=spy_close,
    )
    _require_complete(spy, label="SPY comparison")

    sector = None
    if sector_close is not None:
        sector = _evaluate(
            close=close,
            decision_asof=decision.as_of,
            benchmark_close=sector_close,
        )
        _require_complete(sector, label="sector comparison")

    theme = None
    if theme_control_close is not None:
        theme = _evaluate(
            close=close,
            decision_asof=decision.as_of,
            theme_control_close=theme_control_close,
        )
        _require_complete(theme, label="Theme control comparison")

    evaluated_through = pd.Timestamp(close.dropna().sort_index().index[-1]).isoformat()
    return ShadowOutcomeRecord(
        source_case_hash=decision.case_hash,
        decision_asof=decision.as_of,
        evaluated_through=evaluated_through,
        spy_horizons=spy,
        sector_horizons=sector,
        theme_control_horizons=theme,
        provenance=(
            f"source_case:{decision.case_hash}",
            "decision_lab.outcomes.evaluate_forward_outcomes",
        ),
    )


def run_ablation(
    decision: ShadowRepricingDecision,
    ablation: Ablation,
) -> AblationRecord:
    if not isinstance(ablation, Ablation):
        raise TypeError("unsupported ablation")
    removed = _REMOVED[ablation]
    mechanism_claim_allowed = ablation not in {
        Ablation.NO_ECONOMIC_EXPOSURE_VALIDATION,
        Ablation.NO_MARKET_EXPECTATION_GAP,
    }
    return AblationRecord(
        source_case_hash=decision.case_hash,
        ablation=ablation,
        removed_component=removed,
        mechanism_claim_allowed=mechanism_claim_allowed,
        kill_if_no_degradation=ablation is Ablation.NO_MARKET_EXPECTATION_GAP,
        provenance=(
            f"source_case:{decision.case_hash}",
            f"ablation:{ablation.value}",
        ),
    )
