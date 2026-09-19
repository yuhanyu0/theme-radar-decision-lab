from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Sequence

from .ledger import canonical_hash
from .scanner import ThemeScanResult
from .themes import ThemeDefinition, ThemeLifecycleState


class ResearchTier(str, Enum):
    SCAN_ONLY = "SCAN_ONLY"
    THEME_RESEARCH = "THEME_RESEARCH"
    FULL_DECISION_RESEARCH = "FULL_DECISION_RESEARCH"


@dataclass(frozen=True)
class ResearchAllocation:
    theme_id: str
    as_of: str
    tier: ResearchTier
    scan_priority: float
    effective_priority: float
    scan_novelty_score: float | None
    forced_review: bool
    allocation_reasons: tuple[str, ...]
    source_scan_result_hash: str


@dataclass(frozen=True)
class ResearchBudgetConfig:
    version: str = "0.1"
    calibration_label: str = "uncalibrated"
    theme_research_slots: int = 8
    full_decision_slots: int = 3
    minimum_independent_sources: int = 1
    confidence_floor: float = 0.45
    full_priority_gate: float = 0.65
    full_novelty_gate: float = 0.35
    novelty_floor: float = 0.20
    repeated_no_change_penalty_per_cycle: float = 0.10
    repeated_no_change_penalty_cap: float = 0.30


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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


class ResearchBudgetAllocator:
    def allocate(
        self,
        scan_results: Sequence[ThemeScanResult],
        registry_state: Mapping[str, ThemeDefinition],
        prior_allocations: Sequence[ResearchAllocation],
        config: ResearchBudgetConfig,
        *,
        cycle_as_of: str,
    ) -> list[ResearchAllocation]:
        if config.theme_research_slots < 0 or config.full_decision_slots < 0:
            raise ValueError("research slot counts must be non-negative")

        cycle_dt = _parse_cycle_utc(cycle_as_of)
        for prior in prior_allocations:
            if not _prior_is_strictly_earlier(prior.as_of, cycle_as_of):
                raise ValueError("prior research allocation must be strictly earlier")

        prior_by_theme: dict[str, list[ResearchAllocation]] = {}
        for prior in prior_allocations:
            prior_by_theme.setdefault(prior.theme_id, []).append(prior)
        for history in prior_by_theme.values():
            history.sort(key=lambda item: _parse_utc(item.as_of))

        state: dict[str, dict[str, object]] = {}
        for scan in scan_results:
            if _parse_utc(scan.as_of) > cycle_dt:
                raise ValueError("future-dated scan result")

            reasons: list[str] = []
            definition = registry_state.get(scan.theme_id)
            if definition is None:
                reasons.append("theme not registered")

            penalty_cycles = 0
            for prior in reversed(prior_by_theme.get(scan.theme_id, [])):
                if prior.tier is ResearchTier.SCAN_ONLY:
                    break
                if (
                    prior.scan_novelty_score is None
                    or prior.scan_novelty_score >= config.novelty_floor
                ):
                    break
                penalty_cycles += 1

            decay = min(
                config.repeated_no_change_penalty_cap,
                config.repeated_no_change_penalty_per_cycle * penalty_cycles,
            )
            effective_priority = (
                scan.research_priority
                if scan.forced_review
                else max(0.0, scan.research_priority - decay)
            )
            state[scan.theme_id] = {
                "scan": scan,
                "definition": definition,
                "tier": ResearchTier.SCAN_ONLY,
                "reasons": reasons,
                "effective_priority": effective_priority,
            }

        theme_used = 0
        full_used = 0

        forced = [
            item
            for item in state.values()
            if item["definition"] is not None and item["scan"].forced_review
        ]
        forced.sort(
            key=lambda item: (
                -item["scan"].forced_review_severity,
                -item["effective_priority"],
                -item["scan"].evidence_confidence,
                item["scan"].theme_id,
            )
        )

        for item in forced:
            if (
                theme_used >= config.theme_research_slots
                or full_used >= config.full_decision_slots
            ):
                item["reasons"].append("forced review capacity exhausted")
                continue
            item["tier"] = ResearchTier.FULL_DECISION_RESEARCH
            item["reasons"].extend(item["scan"].forced_review_reasons)
            theme_used += 1
            full_used += 1

        ordinary: list[dict[str, object]] = []
        for item in state.values():
            scan = item["scan"]
            definition = item["definition"]

            if item["tier"] is ResearchTier.FULL_DECISION_RESEARCH:
                continue
            if scan.forced_review:
                continue
            if definition is None:
                continue
            if definition.lifecycle_state is not ThemeLifecycleState.STRENGTHENING:
                item["reasons"].append("theme lifecycle not strengthening")
                continue
            if scan.independent_support_count < config.minimum_independent_sources:
                item["reasons"].append("independent corroboration missing")
                continue
            if scan.independent_contradiction_count > 0:
                item["reasons"].append("independent contradiction unresolved")
                continue
            if scan.evidence_confidence < config.confidence_floor:
                item["reasons"].append("evidence confidence below floor")
                continue
            ordinary.append(item)

        ordinary.sort(
            key=lambda item: (
                -item["effective_priority"],
                -item["scan"].evidence_confidence,
                item["scan"].theme_id,
            )
        )

        for item in ordinary:
            scan = item["scan"]
            if theme_used >= config.theme_research_slots:
                item["reasons"].append("research capacity exhausted")
                continue
            if (
                full_used < config.full_decision_slots
                and item["effective_priority"] >= config.full_priority_gate
                and scan.novelty_score is not None
                and scan.novelty_score >= config.full_novelty_gate
            ):
                item["tier"] = ResearchTier.FULL_DECISION_RESEARCH
                item["reasons"].append("full research gates satisfied")
                theme_used += 1
                full_used += 1

        for item in ordinary:
            if item["tier"] is ResearchTier.FULL_DECISION_RESEARCH:
                continue
            if theme_used >= config.theme_research_slots:
                if "research capacity exhausted" not in item["reasons"]:
                    item["reasons"].append("research capacity exhausted")
                continue
            item["tier"] = ResearchTier.THEME_RESEARCH
            item["reasons"].append("theme research gates satisfied")
            theme_used += 1

        allocations = [
            ResearchAllocation(
                theme_id=item["scan"].theme_id,
                as_of=cycle_as_of,
                tier=item["tier"],
                scan_priority=item["scan"].research_priority,
                effective_priority=item["effective_priority"],
                scan_novelty_score=item["scan"].novelty_score,
                forced_review=item["scan"].forced_review,
                allocation_reasons=tuple(item["reasons"]),
                source_scan_result_hash=canonical_hash(asdict(item["scan"])),
            )
            for item in state.values()
        ]
        tier_rank = {
            ResearchTier.FULL_DECISION_RESEARCH: 0,
            ResearchTier.THEME_RESEARCH: 1,
            ResearchTier.SCAN_ONLY: 2,
        }
        return sorted(
            allocations,
            key=lambda item: (
                tier_rank[item.tier],
                -int(item.forced_review),
                -item.effective_priority,
                item.theme_id,
            ),
        )
