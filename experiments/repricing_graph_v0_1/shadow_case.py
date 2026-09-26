from __future__ import annotations
from dataclasses import asdict, dataclass
from enum import Enum

import numpy as np

from decision_lab.ledger import canonical_hash
from decision_lab.tape import TapeAssessment

from .context import RepricingContext
from .gap import ExpectationGap
from .model import CatalystRecord, KeyUnknown, RepricingCase, ScenarioReturn


@dataclass(frozen=True)
class ShadowRepricingDecision:
    case_hash: str
    as_of: str
    ticker: str
    theme_id: str
    expectation_gap: ExpectationGap | None
    catalyst: CatalystRecord | None
    tape_context: TapeAssessment
    scenarios: tuple[ScenarioReturn, ...]
    strongest_counter_thesis: str
    invalidation_conditions: tuple[str, ...]
    key_unknowns: tuple[KeyUnknown, ...]
    status: str
    warnings: tuple[str, ...]


def _canonical_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def _positive_gap(gap: ExpectationGap | None) -> bool:
    if gap is None:
        return False
    if gap.point is not None:
        return gap.point > 0.0
    return gap.lower is not None and gap.lower > 0.0


def compile_shadow_repricing_decision(
    *,
    case: RepricingCase,
    gap: ExpectationGap | None,
    context: RepricingContext,
    causal_exposure_validated: bool,
    dominant_contradiction: bool = False,
) -> ShadowRepricingDecision:
    catalyst = case.catalysts[0] if case.catalysts else None
    warnings = list(context.warnings)
    if dominant_contradiction:
        status = "INVALIDATED"
        warnings.append("dominant company-specific contradiction")
    elif not causal_exposure_validated:
        status = "RESEARCHING"
        warnings.append("causal economic exposure is not validated")
    elif gap is None:
        status = "RESEARCHING"
        warnings.append("expectation gap is unavailable")
    elif catalyst is None:
        status = "RESEARCHING"
        warnings.append("catalyst is unavailable")
    elif not _positive_gap(gap):
        status = "RESEARCHING"
        warnings.append("expectation gap is not unambiguously positive")
    else:
        status = "CANDIDATE"

    payload = {
        "case": asdict(case),
        "gap": None if gap is None else asdict(gap),
        "context": asdict(context),
        "causal_exposure_validated": bool(causal_exposure_validated),
        "dominant_contradiction": bool(dominant_contradiction),
        "status": status,
    }
    digest = canonical_hash(_canonical_value(payload))
    return ShadowRepricingDecision(
        case_hash=digest,
        as_of=case.as_of,
        ticker=case.ticker,
        theme_id=case.theme_id,
        expectation_gap=gap,
        catalyst=catalyst,
        tape_context=context.tape_assessment,
        scenarios=tuple((*case.upside_scenarios, *case.downside_scenarios)),
        strongest_counter_thesis=case.strongest_counter_thesis,
        invalidation_conditions=case.invalidation_conditions,
        key_unknowns=case.key_unknowns,
        status=status,
        warnings=tuple(warnings),
    )
