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
    horizons: dict[str, dict[str, float | None]]
    alpha_claim_allowed: bool
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class AblationRecord:
    source_case_hash: str
    ablation: Ablation
    expectation_gap_mechanism_present: bool
    incremental_information_observed: bool | None
    kill_signal: bool | None
    note: str
    provenance: tuple[str, ...]


def evaluate_shadow_case(
    *,
    decision: ShadowRepricingDecision,
    close: pd.Series,
    spy_close: pd.Series,
    sector_close: pd.Series | None = None,
    theme_control_close: pd.Series | None = None,
) -> ShadowOutcomeRecord:
    decision_day = decision.as_of[:10]
    base = evaluate_forward_outcomes(
        close=close,
        decision_asof=decision_day,
        benchmark_close=spy_close,
        theme_control_close=theme_control_close,
        horizons=(20, 60),
    )
    sector = None
    if sector_close is not None:
        sector = evaluate_forward_outcomes(
            close=close,
            decision_asof=decision_day,
            benchmark_close=sector_close,
            theme_control_close=None,
            horizons=(20, 60),
        )
    out: dict[str, dict[str, float | None]] = {}
    for h in ("20d", "60d"):
        row = base.get(h)
        if row is None:
            raise ValueError(f"insufficient future sessions for {h}")
        sec_row = None if sector is None else sector.get(h)
        if sector is not None and sec_row is None:
            raise ValueError(f"insufficient sector benchmark sessions for {h}")
        ret = row["return"]
        spy_ret = row["benchmark_return"]
        out[h] = {
            "return": ret,
            "spy_return": spy_ret,
            "spy_excess_return": None if ret is None or spy_ret is None else ret - spy_ret,
            "sector_excess_return": None if sec_row is None else sec_row["theme_relative_return"],
            "theme_excess_return": row["theme_relative_return"],
            "mfe": row["mfe"],
            "mae": row["mae"],
        }
    return ShadowOutcomeRecord(
        source_case_hash=decision.case_hash,
        horizons=out,
        alpha_claim_allowed=False,
        provenance=("decision_lab.outcomes.evaluate_forward_outcomes",),
    )


def run_ablation(
    decision: ShadowRepricingDecision,
    ablation: Ablation,
    *,
    incremental_information_observed: bool | None = None,
) -> AblationRecord:
    if not isinstance(ablation, Ablation):
        raise TypeError("unsupported ablation")
    gap_present = ablation is not Ablation.NO_MARKET_EXPECTATION_GAP
    kill: bool | None = None
    note = "Ablation record only; no performance conclusion from a single case."
    if ablation is Ablation.NO_MARKET_EXPECTATION_GAP and incremental_information_observed is False:
        kill = True
        note = "KILL: removing the expectation-gap component leaves no observed incremental information."
    elif incremental_information_observed is True:
        kill = False
        note = "Incremental information reported by the caller; cohort-level validation is still required."
    return AblationRecord(
        source_case_hash=decision.case_hash,
        ablation=ablation,
        expectation_gap_mechanism_present=gap_present,
        incremental_information_observed=incremental_information_observed,
        kill_signal=kill,
        note=note,
        provenance=(f"ablation:{ablation.value}",),
    )
