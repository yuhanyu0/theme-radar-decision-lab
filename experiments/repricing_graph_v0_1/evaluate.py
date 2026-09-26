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
class AblationRecord:
    source_case_hash: str
    ablation: Ablation
    expectation_gap_present: bool
    can_claim_expectation_gap_mechanism: bool
    notes: tuple[str, ...]


@dataclass(frozen=True)
class ShadowOutcomeRecord:
    source_case_hash: str
    decision_asof: str
    outcomes_by_baseline: dict[str, dict[str, dict | None]]


def evaluate_shadow_case(
    *,
    decision: ShadowRepricingDecision,
    close: pd.Series,
    spy_close: pd.Series | None = None,
    sector_close: pd.Series | None = None,
    theme_control_close: pd.Series | None = None,
) -> ShadowOutcomeRecord:
    horizons = (20, 60)
    outcomes: dict[str, dict[str, dict | None]] = {
        "ABSOLUTE": evaluate_forward_outcomes(
            close=close,
            decision_asof=decision.as_of,
            horizons=horizons,
        )
    }
    if spy_close is not None:
        outcomes["SPY"] = evaluate_forward_outcomes(
            close=close,
            decision_asof=decision.as_of,
            benchmark_close=spy_close,
            horizons=horizons,
        )
    if sector_close is not None:
        outcomes["SECTOR"] = evaluate_forward_outcomes(
            close=close,
            decision_asof=decision.as_of,
            benchmark_close=sector_close,
            horizons=horizons,
        )
    if theme_control_close is not None:
        outcomes["THEME_CONTROL"] = evaluate_forward_outcomes(
            close=close,
            decision_asof=decision.as_of,
            benchmark_close=theme_control_close,
            horizons=horizons,
        )
    return ShadowOutcomeRecord(
        source_case_hash=decision.case_hash,
        decision_asof=decision.as_of,
        outcomes_by_baseline=outcomes,
    )


def run_ablation(
    decision: ShadowRepricingDecision,
    ablation: Ablation,
) -> AblationRecord:
    if not isinstance(ablation, Ablation):
        raise TypeError("unsupported ablation")
    gap_present = (
        decision.expectation_gap is not None
        and ablation is not Ablation.NO_MARKET_EXPECTATION_GAP
    )
    notes = (
        "central expectation-gap component removed",
    ) if ablation is Ablation.NO_MARKET_EXPECTATION_GAP else ()
    return AblationRecord(
        source_case_hash=decision.case_hash,
        ablation=ablation,
        expectation_gap_present=gap_present,
        can_claim_expectation_gap_mechanism=gap_present,
        notes=notes,
    )


def central_ablation_kill_signal(
    *,
    full_metric: float,
    no_gap_metric: float,
    tolerance: float = 0.0,
) -> bool:
    return no_gap_metric >= full_metric - tolerance
