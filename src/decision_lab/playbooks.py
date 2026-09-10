from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

PLAYBOOKS = ("A", "B", "C", "D", "E", "F", "G", "H", "NoTrade")


@dataclass(frozen=True)
class PlaybookRouting:
    raw_scores: Mapping[str, float]
    normalized_scores: Mapping[str, float]
    selected_playbook: str
    action: str
    probability_is_calibrated: bool
    rationale: tuple[str, ...]


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    cleaned = {k: max(0.0, float(scores.get(k, 0.0))) for k in PLAYBOOKS}
    total = sum(cleaned.values())
    if total <= 0:
        return {k: (1.0 if k == "NoTrade" else 0.0) for k in PLAYBOOKS}
    return {k: v / total for k, v in cleaned.items()}


def route_playbooks(
    *,
    theme_key: bool,
    tape_state: str,
    tape_stage: str,
    fundamentals_intact: bool = False,
    true_catalyst: bool = False,
    breakout_confirmed: bool = False,
    squeeze_confirmed: bool = False,
    stable_regime: bool = False,
    overheated_without_upgrade: bool = False,
    pair_divergence: bool = False,
    structural_repricing: bool = False,
    world_confidence: str = "unknown",
) -> PlaybookRouting:
    """Route one observed state into A-H plus an explicit NoTrade competitor.

    Scores are *match scores*, not calibrated probabilities. Calibration should only be
    enabled after enough immutable live decisions exist for reliability/Brier analysis.
    """
    scores = {k: 0.0 for k in PLAYBOOKS}
    reasons: list[str] = []

    # Baseline caution. NoTrade is not an error state; it is a first-class competitor.
    scores["NoTrade"] = 0.35

    if not theme_key:
        scores["NoTrade"] += 0.70
        reasons.append("theme key is not satisfied")
    else:
        reasons.append("theme key is satisfied")

    if world_confidence.lower() in {"low", "weak"}:
        scores["NoTrade"] += 0.25
        reasons.append("low world confidence raises the action threshold")

    if tape_state in {"falling_knife", "failed_rebound"} or tape_stage == "B0":
        scores["NoTrade"] += 1.50
        reasons.append("Tape path is still failed/falling; B and C execution are blocked")
    elif tape_stage == "B1" or tape_state == "attempted_base":
        scores["B"] += 0.45
        if fundamentals_intact:
            scores["C"] += 0.25
        reasons.append("base formation is visible but not yet reclaimed")
    elif tape_stage == "B2" or tape_state in {"higher_low", "reclaim"}:
        scores["B"] += 1.00
        if fundamentals_intact:
            scores["C"] += 0.45
        reasons.append("higher-low/reclaim path supports an early B candidate")
    elif tape_stage == "B3" or tape_state == "clean_retest":
        scores["B"] += 1.50
        if fundamentals_intact:
            scores["C"] += 0.30
        reasons.append("clean retest is the highest-quality B path state")

    if true_catalyst and breakout_confirmed:
        scores["A"] += 1.25
        reasons.append("true catalyst plus breakout supports A")

    # C must not fire directly from a selloff/fundamental-intact state.
    if fundamentals_intact and tape_state not in {"falling_knife", "failed_rebound"}:
        if tape_stage in {"B1", "B2", "B3"} or tape_state in {
            "attempted_base",
            "higher_low",
            "reclaim",
            "clean_retest",
        }:
            scores["C"] += 0.35
            reasons.append("fundamentals intact and Tape has stabilized enough for C consideration")

    if squeeze_confirmed or tape_state == "squeeze":
        scores["D"] += 0.90
        reasons.append("compression state supports D")

    if stable_regime:
        scores["E"] += 0.45
        reasons.append("stable regime allows E carry to compete")

    if overheated_without_upgrade or tape_state == "extended":
        scores["F"] += 0.80
        reasons.append("extended/overheated move raises F fade probability")

    if pair_divergence:
        scores["G"] += 0.75
        reasons.append("same-chain relative divergence supports G")

    if structural_repricing:
        scores["H"] += 0.80
        reasons.append("valuation/KPI anchor shift supports H")
        if tape_stage == "B3" or tape_state == "clean_retest":
            scores["B"] += 0.45
            reasons.append("H is being expressed through a confirmed B retest")

    normalized = _normalize(scores)
    selected = max(normalized, key=normalized.get)

    if tape_state in {"falling_knife", "failed_rebound"} or selected == "NoTrade":
        action = "BLOCKED"
    elif not theme_key:
        action = "WATCH_ONLY"
    elif tape_stage == "B3" and normalized.get("B", 0.0) >= normalized.get("NoTrade", 0.0):
        action = "BUILD_ON_RETEST"
    elif tape_stage == "B2" and normalized.get("B", 0.0) >= normalized.get("NoTrade", 0.0):
        action = "AGGRESSIVE_PROBE"
    else:
        action = "WATCH_ONLY"

    # Raw match scores intentionally stay uncalibrated in v0.1.
    return PlaybookRouting(
        raw_scores=scores,
        normalized_scores=normalized,
        selected_playbook=selected,
        action=action,
        probability_is_calibrated=False,
        rationale=tuple(reasons),
    )
