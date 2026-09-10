from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from .ledger import canonical_hash

SourceType = Literal[
    "market_data",
    "sec_filing",
    "company_ir",
    "official_macro",
    "industry_primary",
    "reputable_reporting",
    "radar_model_output",
    "derived_feature",
]

# Model output is intentionally lower-trust than raw/primary evidence.
SOURCE_PRIORITY: dict[str, int] = {
    "sec_filing": 100,
    "company_ir": 95,
    "official_macro": 95,
    "industry_primary": 90,
    "market_data": 90,
    "reputable_reporting": 75,
    "derived_feature": 60,
    "radar_model_output": 50,
}


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    observed_at: str
    source_type: SourceType
    source_ref: str
    fact_type: str
    payload: dict[str, Any]
    retrieved_at: str | None = None
    market_asof: str | None = None
    ticker: str | None = None
    theme: str | None = None
    source_hash: str | None = None
    is_observed_fact: bool = True
    model_version: str | None = None
    notes: str | None = None

    @property
    def source_priority(self) -> int:
        return SOURCE_PRIORITY[self.source_type]

    def with_hash(self) -> "EvidenceRecord":
        if self.source_hash:
            return self
        payload = asdict(self)
        payload["source_hash"] = None
        digest = canonical_hash(payload)
        return EvidenceRecord(**{**payload, "source_hash": digest})


def make_evidence(
    *,
    source_type: SourceType,
    source_ref: str,
    fact_type: str,
    payload: dict[str, Any],
    observed_at: str,
    ticker: str | None = None,
    theme: str | None = None,
    market_asof: str | None = None,
    is_observed_fact: bool = True,
    model_version: str | None = None,
    notes: str | None = None,
) -> EvidenceRecord:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    raw_id = canonical_hash(
        {
            "source_type": source_type,
            "source_ref": source_ref,
            "fact_type": fact_type,
            "observed_at": observed_at,
            "ticker": ticker,
            "theme": theme,
        }
    )[:20]
    return EvidenceRecord(
        evidence_id=f"ev_{raw_id}",
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        market_asof=market_asof,
        ticker=ticker,
        theme=theme,
        source_type=source_type,
        source_ref=source_ref,
        fact_type=fact_type,
        payload=payload,
        is_observed_fact=is_observed_fact,
        model_version=model_version,
        notes=notes,
    ).with_hash()


def evidence_divergence(
    independent_value: float | None,
    model_value: float | None,
    *,
    tolerance: float,
) -> str:
    if independent_value is None or model_value is None:
        return "insufficient_overlap"
    delta = independent_value - model_value
    if abs(delta) <= tolerance:
        return "aligned"
    return "independent_stronger" if delta > 0 else "model_stronger"
