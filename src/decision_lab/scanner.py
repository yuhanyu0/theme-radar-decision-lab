from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from statistics import mean
from typing import Literal

import yaml

from .evidence import SourceType
from .ledger import canonical_hash
from .themes import ThemeDefinition, ThemeLifecycleState


class SupportDirection(str, Enum):
    SUPPORTING = "supporting"
    NEUTRAL = "neutral"
    CONTRADICTING = "contradicting"


@dataclass(frozen=True)
class ThemeScanObservation:
    theme_id: str
    as_of: str
    source_type: SourceType
    source_ref: str
    discovery_signal: float | None = None
    structure_signal: float | None = None
    persistence_signal: float | None = None
    breadth_signal: float | None = None
    relative_strength_signal: float | None = None
    volatility_signal: float | None = None
    novelty_signal: float | None = None
    support_direction: SupportDirection = SupportDirection.NEUTRAL
    evidence_refs: tuple[str, ...] = ()
    is_independent: bool = False
    observed_or_inferred: Literal["observed", "inferred"] = "observed"
    notes: str | None = None


@dataclass(frozen=True)
class ScannerConfig:
    version: str = "0.1"
    calibration_label: str = "uncalibrated"
    stale_after_days: int = 5
    source_weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "sec_filing": 1.00,
            "company_ir": 1.00,
            "official_macro": 1.00,
            "industry_primary": 0.95,
            "market_data": 0.90,
            "reputable_reporting": 0.75,
            "derived_feature": 0.60,
            "radar_model_output": 0.50,
        }
    )
    component_weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "discovery": 0.15,
            "structural": 0.20,
            "persistence": 0.15,
            "breadth": 0.10,
            "relative_strength": 0.10,
            "novelty": 0.15,
            "evidence_confidence": 0.15,
        }
    )
    contradiction_staleness_penalty: float = 0.25
    strengthening_structure_gate: float = 0.60
    strengthening_persistence_gate: float = 0.60
    weakening_low_persistence_gate: float = 0.35
    weakening_low_breadth_gate: float = 0.35
    hard_contradiction_ratio: float = 0.50
    dormant_no_support_cycles: int = 3



def load_scanner_config(path: str | Path) -> ScannerConfig:
    payload = dict(yaml.safe_load(Path(path).read_text()) or {})
    payload["calibration_label"] = "uncalibrated"
    return ScannerConfig(**payload)


@dataclass(frozen=True)
class ThemeScanResult:
    theme_id: str
    as_of: str
    discovery_score: float | None
    structural_score: float | None
    persistence_score: float | None
    breadth_score: float | None
    relative_strength_score: float | None
    novelty_score: float | None
    evidence_confidence: float
    independent_support_count: int
    independent_contradiction_count: int
    lifecycle_recommendation: str
    research_priority: float
    forced_review: bool
    forced_review_severity: int
    forced_review_reasons: tuple[str, ...]
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    config_hash: str
    registry_version: str | None
    prior_result_refs: tuple[str, ...]


_COMPONENT_FIELDS = {
    "discovery": "discovery_signal",
    "structural": "structure_signal",
    "persistence": "persistence_signal",
    "breadth": "breadth_signal",
    "relative_strength": "relative_strength_signal",
    "novelty": "novelty_signal",
}


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _is_date_only(value: str) -> bool:
    return "T" not in value and " " not in value


def _parse_cycle_utc(value: str) -> datetime:
    dt = _parse_utc(value)
    if _is_date_only(value):
        return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


def _prior_is_strictly_earlier(prior_as_of: str, cycle_as_of: str) -> bool:
    prior_dt = _parse_utc(prior_as_of)
    if _is_date_only(cycle_as_of):
        return prior_dt.date() < _parse_utc(cycle_as_of).date()
    return prior_dt < _parse_utc(cycle_as_of)


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _validate_observation(obs: ThemeScanObservation, cycle_dt: datetime) -> None:
    if _parse_utc(obs.as_of) > cycle_dt:
        raise ValueError("future-dated observation")
    if obs.source_type == "radar_model_output" and obs.is_independent:
        raise ValueError("radar_model_output cannot be independent")
    for name in (
        "discovery_signal",
        "structure_signal",
        "persistence_signal",
        "breadth_signal",
        "relative_strength_signal",
        "volatility_signal",
        "novelty_signal",
    ):
        value = getattr(obs, name)
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be in [0,1]")


def _collapse_sources(
    observations: Sequence[ThemeScanObservation],
) -> dict[str, list[ThemeScanObservation]]:
    grouped: dict[str, list[ThemeScanObservation]] = {}
    for obs in observations:
        grouped.setdefault(obs.source_ref, []).append(obs)
    return grouped


def _component_score(
    grouped_sources: Mapping[str, Sequence[ThemeScanObservation]],
    *,
    field_name: str,
    config: ScannerConfig,
) -> float | None:
    weighted: list[tuple[float, float]] = []
    for rows in grouped_sources.values():
        values = [
            float(value)
            for row in rows
            if (value := getattr(row, field_name)) is not None
        ]
        if not values:
            continue
        source_value = mean(values)
        source_weight = max(
            float(config.source_weights.get(str(row.source_type), 0.0))
            for row in rows
        )
        if source_weight <= 0.0:
            continue
        weighted.append((source_value, source_weight))
    if not weighted:
        return None
    numerator = sum(value * weight for value, weight in weighted)
    denominator = sum(weight for _, weight in weighted)
    return _clip01(numerator / denominator)


def _distinct_independent_sources(
    grouped_sources: Mapping[str, Sequence[ThemeScanObservation]],
) -> dict[str, Sequence[ThemeScanObservation]]:
    return {
        source_ref: rows
        for source_ref, rows in grouped_sources.items()
        if any(row.is_independent for row in rows)
    }


def _source_direction(
    rows: Sequence[ThemeScanObservation],
) -> SupportDirection:
    directions = {row.support_direction for row in rows if row.is_independent}
    if SupportDirection.CONTRADICTING in directions:
        return SupportDirection.CONTRADICTING
    if SupportDirection.SUPPORTING in directions:
        return SupportDirection.SUPPORTING
    return SupportDirection.NEUTRAL


def _evidence_confidence(
    independent_sources: Mapping[str, Sequence[ThemeScanObservation]],
    *,
    cycle_dt: datetime,
    config: ScannerConfig,
) -> float:
    if not independent_sources:
        return 0.0

    directions = {
        source_ref: _source_direction(rows)
        for source_ref, rows in independent_sources.items()
    }
    support_count = sum(
        direction is SupportDirection.SUPPORTING
        for direction in directions.values()
    )
    contradiction_count = sum(
        direction is SupportDirection.CONTRADICTING
        for direction in directions.values()
    )
    coverage = min(1.0, len(independent_sources) / 2.0)
    agreement = 1.0 - contradiction_count / max(
        1, support_count + contradiction_count
    )

    freshness_values: list[float] = []
    for rows in independent_sources.values():
        source_dt = max(_parse_utc(row.as_of) for row in rows)
        age_days = max(0.0, (cycle_dt - source_dt).total_seconds() / 86400.0)
        if config.stale_after_days <= 0:
            freshness_values.append(1.0 if age_days <= 0.0 else 0.0)
        else:
            freshness_values.append(
                max(0.0, 1.0 - age_days / config.stale_after_days)
            )
    freshness = mean(freshness_values)
    return _clip01(0.40 * coverage + 0.30 * agreement + 0.30 * freshness)


def _stale_ratio(
    grouped_sources: Mapping[str, Sequence[ThemeScanObservation]],
    *,
    cycle_dt: datetime,
    config: ScannerConfig,
) -> float:
    if not grouped_sources:
        return 0.0
    stale = 0
    for rows in grouped_sources.values():
        source_dt = max(_parse_utc(row.as_of) for row in rows)
        age_days = max(0.0, (cycle_dt - source_dt).total_seconds() / 86400.0)
        if age_days > config.stale_after_days:
            stale += 1
    return stale / len(grouped_sources)


def _priority(
    *,
    scores: Mapping[str, float | None],
    evidence_confidence: float,
    contradiction_ratio: float,
    stale_ratio: float,
    config: ScannerConfig,
) -> float:
    substantive = {name: value for name, value in scores.items() if value is not None}
    if not substantive:
        return 0.0

    positive = {**substantive, "evidence_confidence": evidence_confidence}
    numerator = 0.0
    denominator = 0.0
    for name, value in positive.items():
        weight = float(config.component_weights.get(name, 0.0))
        if weight <= 0.0:
            continue
        numerator += weight * float(value)
        denominator += weight
    base_priority = 0.0 if denominator == 0.0 else numerator / denominator
    penalty = max(contradiction_ratio, stale_ratio)
    return _clip01(base_priority - config.contradiction_staleness_penalty * penalty)


def _history_by_theme(
    prior_results: Sequence[ThemeScanResult],
    *,
    cycle_as_of: str,
) -> dict[str, list[ThemeScanResult]]:
    history: dict[str, list[ThemeScanResult]] = {}
    for prior in prior_results:
        if not _prior_is_strictly_earlier(prior.as_of, cycle_as_of):
            raise ValueError("prior scan result must be strictly earlier")
        history.setdefault(prior.theme_id, []).append(prior)
    for rows in history.values():
        rows.sort(key=lambda item: _parse_utc(item.as_of))
    return history


def _forced_review(
    *,
    definition: ThemeDefinition | None,
    contradiction_ratio: float,
    independent_contradiction_count: int,
    persistence_score: float | None,
    breadth_score: float | None,
    config: ScannerConfig,
) -> tuple[bool, int, tuple[str, ...]]:
    reasons: list[str] = []
    severity = 0

    if (
        independent_contradiction_count > 0
        and contradiction_ratio >= config.hard_contradiction_ratio
    ):
        reasons.append("independent contradiction")
        severity = 3

    if (
        definition is not None
        and definition.lifecycle_state
        in (ThemeLifecycleState.STRENGTHENING, ThemeLifecycleState.MATURE)
        and persistence_score is not None
        and breadth_score is not None
        and persistence_score < config.weakening_low_persistence_gate
        and breadth_score < config.weakening_low_breadth_gate
    ):
        reasons.append("lifecycle deterioration")
        severity = max(severity, 2)

    return bool(reasons), severity, tuple(reasons)


def _lifecycle_recommendation(
    *,
    definition: ThemeDefinition | None,
    history: Sequence[ThemeScanResult],
    independent_support_count: int,
    contradiction_ratio: float,
    independent_contradiction_count: int,
    structural_score: float | None,
    persistence_score: float | None,
    breadth_score: float | None,
    config: ScannerConfig,
) -> str:
    if definition is None:
        return "discovery"

    state = definition.lifecycle_state
    if (
        state in (ThemeLifecycleState.DISCOVERY, ThemeLifecycleState.FORMING)
        and independent_support_count >= 1
        and independent_contradiction_count == 0
        and structural_score is not None
        and persistence_score is not None
        and structural_score >= config.strengthening_structure_gate
        and persistence_score >= config.strengthening_persistence_gate
    ):
        return "strengthening"

    if (
        state in (ThemeLifecycleState.STRENGTHENING, ThemeLifecycleState.MATURE)
        and independent_contradiction_count > 0
        and contradiction_ratio >= config.hard_contradiction_ratio
    ):
        return "weakening"

    if (
        state in (ThemeLifecycleState.STRENGTHENING, ThemeLifecycleState.MATURE)
        and persistence_score is not None
        and breadth_score is not None
        and persistence_score < config.weakening_low_persistence_gate
        and breadth_score < config.weakening_low_breadth_gate
    ):
        return "weakening"

    dormant_window = config.dormant_no_support_cycles
    if (
        state is ThemeLifecycleState.WEAKENING
        and dormant_window > 0
        and independent_support_count == 0
        and len(history) >= dormant_window
        and all(item.independent_support_count == 0 for item in history[-dormant_window:])
    ):
        return "dormant"

    return "no_change"


def rank_themes(
    observations: Sequence[ThemeScanObservation],
    registry_state: Mapping[str, ThemeDefinition],
    prior_results: Sequence[ThemeScanResult],
    config: ScannerConfig,
    *,
    cycle_as_of: str,
) -> list[ThemeScanResult]:
    cycle_dt = _parse_cycle_utc(cycle_as_of)
    history = _history_by_theme(prior_results, cycle_as_of=cycle_as_of)

    by_theme: dict[str, list[ThemeScanObservation]] = {}
    for obs in observations:
        _validate_observation(obs, cycle_dt)
        by_theme.setdefault(obs.theme_id, []).append(obs)

    config_hash = canonical_hash(asdict(config))
    results: list[ThemeScanResult] = []

    for theme_id, rows in by_theme.items():
        grouped_sources = _collapse_sources(rows)
        independent_sources = _distinct_independent_sources(grouped_sources)
        directions = {
            source_ref: _source_direction(source_rows)
            for source_ref, source_rows in independent_sources.items()
        }
        independent_support_count = sum(
            direction is SupportDirection.SUPPORTING for direction in directions.values()
        )
        independent_contradiction_count = sum(
            direction is SupportDirection.CONTRADICTING
            for direction in directions.values()
        )
        contradiction_ratio = independent_contradiction_count / max(
            1, independent_support_count + independent_contradiction_count
        )
        confidence = _evidence_confidence(
            independent_sources,
            cycle_dt=cycle_dt,
            config=config,
        )
        scores = {
            component: _component_score(
                grouped_sources,
                field_name=field_name,
                config=config,
            )
            for component, field_name in _COMPONENT_FIELDS.items()
        }
        priority = _priority(
            scores=scores,
            evidence_confidence=confidence,
            contradiction_ratio=contradiction_ratio,
            stale_ratio=_stale_ratio(
                grouped_sources,
                cycle_dt=cycle_dt,
                config=config,
            ),
            config=config,
        )

        definition = registry_state.get(theme_id)
        theme_history = history.get(theme_id, [])
        forced_review, forced_severity, forced_reasons = _forced_review(
            definition=definition,
            contradiction_ratio=contradiction_ratio,
            independent_contradiction_count=independent_contradiction_count,
            persistence_score=scores["persistence"],
            breadth_score=scores["breadth"],
            config=config,
        )
        lifecycle = _lifecycle_recommendation(
            definition=definition,
            history=theme_history,
            independent_support_count=independent_support_count,
            contradiction_ratio=contradiction_ratio,
            independent_contradiction_count=independent_contradiction_count,
            structural_score=scores["structural"],
            persistence_score=scores["persistence"],
            breadth_score=scores["breadth"],
            config=config,
        )
        evidence_refs = tuple(sorted({ref for row in rows for ref in row.evidence_refs}))
        prior_refs = tuple(canonical_hash(asdict(item)) for item in theme_history)

        results.append(
            ThemeScanResult(
                theme_id=theme_id,
                as_of=cycle_as_of,
                discovery_score=scores["discovery"],
                structural_score=scores["structural"],
                persistence_score=scores["persistence"],
                breadth_score=scores["breadth"],
                relative_strength_score=scores["relative_strength"],
                novelty_score=scores["novelty"],
                evidence_confidence=confidence,
                independent_support_count=independent_support_count,
                independent_contradiction_count=independent_contradiction_count,
                lifecycle_recommendation=lifecycle,
                research_priority=priority,
                forced_review=forced_review,
                forced_review_severity=forced_severity,
                forced_review_reasons=forced_reasons,
                reasons=(),
                evidence_refs=evidence_refs,
                config_hash=config_hash,
                registry_version=None if definition is None else definition.version,
                prior_result_refs=prior_refs,
            )
        )

    return sorted(
        results,
        key=lambda item: (
            not item.forced_review,
            -item.forced_review_severity,
            -item.research_priority,
            -item.evidence_confidence,
            item.theme_id,
        ),
    )
