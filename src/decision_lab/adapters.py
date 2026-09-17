from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


RawFactValue = float | int | str | None


@dataclass(frozen=True)
class CompanyEvidenceInput:
    ticker: str
    as_of: str
    raw_facts: Mapping[str, RawFactValue]
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedCompanyEvidence:
    ticker: str
    as_of: str
    growth: float | None = None
    margin_quality: float | None = None
    demand_visibility: float | None = None
    order_or_contract_visibility: float | None = None
    capital_intensity: float | None = None
    cash_generation: float | None = None
    balance_sheet_strength: float | None = None
    customer_concentration: float | None = None
    supply_constraint: float | None = None
    guidance_revision: float | None = None
    valuation_anchor_change: float | None = None
    thesis_risk: float | None = None
    source_coverage: str = "raw_only"
    provenance: tuple[str, ...] = ()
    raw_facts: Mapping[str, RawFactValue] = field(default_factory=dict)


class CompanyEvidenceAdapter(Protocol):
    def normalize(self, source: CompanyEvidenceInput) -> NormalizedCompanyEvidence: ...


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _linear(value: float | None, *, midpoint: float, span: float) -> float | None:
    if value is None:
        return None
    return _clip01(0.5 + (float(value) - midpoint) / span)


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class GenericEvidenceAdapter:
    def normalize(self, source: CompanyEvidenceInput) -> NormalizedCompanyEvidence:
        return NormalizedCompanyEvidence(
            ticker=source.ticker.upper(),
            as_of=source.as_of,
            source_coverage="raw_only",
            provenance=source.provenance,
            raw_facts=dict(source.raw_facts),
        )


class IndustrialsInfrastructureAdapter:
    def normalize(self, source: CompanyEvidenceInput) -> NormalizedCompanyEvidence:
        facts = source.raw_facts
        revenue_growth = _number(facts.get("revenue_growth"))
        gross_margin = _number(facts.get("gross_margin"))
        backlog_growth = _number(facts.get("backlog_growth"))
        order_growth = _number(facts.get("order_growth"))
        capex_to_sales = _number(facts.get("capex_to_sales"))
        fcf_margin = _number(facts.get("fcf_margin"))
        leverage = _number(facts.get("net_debt_to_ebitda"))
        concentration = _number(facts.get("top_customer_share"))
        guidance = _number(facts.get("guidance_revision"))

        demand_candidates = [
            score
            for score in (
                _linear(backlog_growth, midpoint=0.0, span=0.60),
                _linear(order_growth, midpoint=0.0, span=0.60),
            )
            if score is not None
        ]
        demand = max(demand_candidates) if demand_candidates else None

        return NormalizedCompanyEvidence(
            ticker=source.ticker.upper(),
            as_of=source.as_of,
            growth=_linear(revenue_growth, midpoint=0.0, span=0.40),
            margin_quality=None if gross_margin is None else _clip01(gross_margin / 0.50),
            demand_visibility=demand,
            order_or_contract_visibility=demand,
            capital_intensity=(
                None if capex_to_sales is None else _clip01(capex_to_sales / 0.25)
            ),
            cash_generation=None if fcf_margin is None else _clip01(fcf_margin / 0.20),
            balance_sheet_strength=(
                None if leverage is None else _clip01(1.0 - leverage / 4.0)
            ),
            customer_concentration=(
                None if concentration is None else _clip01(concentration)
            ),
            guidance_revision=_linear(guidance, midpoint=0.0, span=0.20),
            thesis_risk=None if concentration is None else _clip01(concentration),
            source_coverage="industrials_core",
            provenance=source.provenance,
            raw_facts=dict(facts),
        )
