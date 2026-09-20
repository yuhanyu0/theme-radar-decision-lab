from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from statistics import mean

from .ledger import canonical_hash
from .replay import ReplayCycleResult, ReplayStatus, ReplayThemeRecord
from .replay_archive import ReplayArchiveRecord, build_replay_archive_record
from .research_budget import ResearchTier

SCHEMA_VERSION = "0.1"
EVALUATION_SCOPE = "evidence_evolution_and_descriptive_system_transition"
LIMITATIONS = (
    "future system state is descriptive, not independent ground truth",
    "budget config identity is not recoverable from ReplayCycleResult alone",
    "allocation tier records routing intent, not proof downstream research executed",
    "research allocation is not evaluated as a directional price prediction",
)


class EvidenceClass(str, Enum):
    NO_INDEPENDENT = "NO_INDEPENDENT"
    SUPPORT_ONLY = "SUPPORT_ONLY"
    CONTRADICTION_PRESENT = "CONTRADICTION_PRESENT"
    NEUTRAL_ONLY = "NEUTRAL_ONLY"
    MIXED = "MIXED"


class FuturePresence(str, Enum):
    PRESENT = "PRESENT"
    NOT_PRESENT = "NOT_PRESENT"
    RIGHT_CENSORED = "RIGHT_CENSORED"


class RoutingIntent(str, Enum):
    NO_OBSERVATION = "NO_OBSERVATION"
    SCAN_ONLY = "SCAN_ONLY"
    ORDINARY_THEME_RESEARCH = "ORDINARY_THEME_RESEARCH"
    ORDINARY_FULL_RESEARCH = "ORDINARY_FULL_RESEARCH"
    FORCED_FULL_REVIEW = "FORCED_FULL_REVIEW"
    FORCED_REVIEW_CAPACITY_MISSED = "FORCED_REVIEW_CAPACITY_MISSED"


class ContradictionTransition(str, Enum):
    ABSENT = "ABSENT"
    EMERGED = "EMERGED"
    PERSISTED = "PERSISTED"
    RESOLVED = "RESOLVED"
    UNASSESSED = "UNASSESSED"


class TierTransition(str, Enum):
    SAME = "SAME"
    ESCALATED = "ESCALATED"
    DEESCALATED = "DEESCALATED"
    UNASSESSED = "UNASSESSED"


@dataclass(frozen=True)
class IndependentEvidenceState:
    evidence_class: EvidenceClass
    independent_source_count: int
    supporting_source_count: int
    contradicting_source_count: int
    neutral_source_count: int
    supporting_source_refs: tuple[str, ...]
    contradicting_source_refs: tuple[str, ...]
    neutral_source_refs: tuple[str, ...]


@dataclass(frozen=True)
class ReplayCohortTransition:
    source_cycle_index: int
    future_cycle_index: int | None
    source_cycle_as_of: str
    future_cycle_as_of: str | None
    horizon_cycles: int
    source_archive_record_hash: str
    future_archive_record_hash: str | None
    theme_id: str
    routing_intent: RoutingIntent
    source_registered: bool
    future_presence: FuturePresence
    future_registered: bool | None
    source_evidence_state: IndependentEvidenceState
    future_evidence_state: IndependentEvidenceState | None
    support_delta: int | None
    contradiction_delta: int | None
    contradiction_transition: ContradictionTransition
    evidence_class_changed: bool | None
    source_replay_status: ReplayStatus
    future_replay_status: ReplayStatus | None
    source_scanner_config_hash: str | None
    future_scanner_config_hash: str | None
    scanner_config_changed: bool | None
    source_priority: float | None
    future_priority: float | None
    priority_delta: float | None
    source_confidence: float | None
    future_confidence: float | None
    confidence_delta: float | None
    source_novelty: float | None
    future_novelty: float | None
    novelty_delta: float | None
    source_lifecycle: str | None
    future_lifecycle: str | None
    source_forced_review: bool | None
    future_forced_review: bool | None
    source_tier: ResearchTier | None
    future_tier: ResearchTier | None
    tier_transition: TierTransition


@dataclass(frozen=True)
class ReplayCohortSummary:
    routing_intent: RoutingIntent
    horizon_cycles: int
    source_n: int
    future_cycle_available_n: int
    right_censored_n: int
    future_present_n: int
    future_not_present_n: int
    future_independent_evidence_n: int
    contradiction_unassessed_n: int
    contradiction_absent_n: int
    contradiction_emerged_n: int
    contradiction_persisted_n: int
    contradiction_resolved_n: int
    source_independent_evidence_n: int
    evidence_class_comparable_n: int
    evidence_class_changed_n: int
    tier_unassessed_n: int
    tier_same_n: int
    tier_escalated_n: int
    tier_deescalated_n: int
    forced_review_unassessed_n: int
    forced_review_inactive_n: int
    forced_review_emerged_n: int
    forced_review_persisted_n: int
    forced_review_resolved_n: int
    scanner_config_unassessed_n: int
    scanner_config_same_n: int
    scanner_config_changed_n: int
    priority_delta_n: int
    mean_priority_delta: float | None
    confidence_delta_n: int
    mean_confidence_delta: float | None
    novelty_delta_n: int
    mean_novelty_delta: float | None


@dataclass(frozen=True)
class ReplayCohortResult:
    schema_version: str
    evaluation_scope: str
    horizons: tuple[int, ...]
    cycles: tuple[str, ...]
    archive_record_hashes: tuple[str, ...]
    transitions: tuple[ReplayCohortTransition, ...]
    summaries: tuple[ReplayCohortSummary, ...]
    limitations: tuple[str, ...]
    input_hash: str
    result_hash: str


def _parse_cycle_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    if "T" not in value and " " not in value:
        return dt.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )
    return dt


def _normalize_horizons(values: Sequence[int]) -> tuple[int, ...]:
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("cohort horizons must be positive integers")
        normalized.append(value)
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate cohort horizon")
    return tuple(sorted(normalized))


def _validate_archive_record(record: ReplayArchiveRecord) -> None:
    rebuilt = build_replay_archive_record(record.replay_result)
    if rebuilt != record:
        raise ValueError("invalid replay archive record")


def _unique_by_theme(items) -> dict[str, object]:
    output: dict[str, object] = {}
    for item in items:
        if item.theme_id in output:
            raise ValueError("inconsistent replay theme record")
        output[item.theme_id] = item
    return output


def _validate_replay_semantics(result: ReplayCycleResult) -> None:
    batches = _unique_by_theme(result.market_batches)
    scans = _unique_by_theme(result.scan_results)
    allocations = _unique_by_theme(result.allocations)
    records = _unique_by_theme(result.theme_records)

    routed_ids = {
        item.theme_id
        for item in result.theme_records
        if item.replay_status is ReplayStatus.ROUTED
    }
    registered_ids = {
        item.theme_id
        for item in result.theme_records
        if item.registered
    }

    if set(scans) != routed_ids or set(allocations) != routed_ids:
        raise ValueError("inconsistent replay theme record")
    if set(batches) != registered_ids:
        raise ValueError("inconsistent replay theme record")

    scanner_hashes = {item.config_hash for item in result.scan_results}
    if len(scanner_hashes) > 1:
        raise ValueError("multiple scanner config hashes in replay cycle")

    for batch in result.market_batches:
        if batch.cycle_as_of != result.cycle_as_of:
            raise ValueError("inconsistent replay theme record")

    for scan in result.scan_results:
        if scan.as_of != result.cycle_as_of:
            raise ValueError("inconsistent replay theme record")

    for allocation in result.allocations:
        if allocation.as_of != result.cycle_as_of:
            raise ValueError("inconsistent replay theme record")

    for item in result.theme_records:
        if item.replay_status is ReplayStatus.NO_OBSERVATION:
            if (
                not item.registered
                or item.scan_result is not None
                or item.allocation is not None
            ):
                raise ValueError("inconsistent replay theme record")
        elif item.replay_status is ReplayStatus.ROUTED:
            if item.scan_result is None or item.allocation is None:
                raise ValueError("inconsistent replay theme record")
            if scans[item.theme_id] != item.scan_result:
                raise ValueError("inconsistent replay theme record")
            if allocations[item.theme_id] != item.allocation:
                raise ValueError("inconsistent replay theme record")
            expected_scan_hash = canonical_hash(asdict(item.scan_result))
            if item.allocation.source_scan_result_hash != expected_scan_hash:
                raise ValueError("allocation scan-result hash mismatch")
        else:
            raise ValueError("inconsistent replay theme record")

        if item.registered:
            if item.market_batch is None:
                raise ValueError("inconsistent replay theme record")
            if batches[item.theme_id] != item.market_batch:
                raise ValueError("inconsistent replay theme record")
        elif item.market_batch is not None:
            raise ValueError("inconsistent replay theme record")

    for observation in result.combined_observations:
        if observation.theme_id not in records:
            raise ValueError("observation theme missing from replay records")


def _normalize_records(
    records: Sequence[ReplayArchiveRecord],
) -> tuple[ReplayArchiveRecord, ...]:
    seen_hashes: set[str] = set()
    rows: list[tuple[datetime, ReplayArchiveRecord]] = []
    for record in records:
        if record.archive_record_hash in seen_hashes:
            raise ValueError("duplicate replay archive record")
        seen_hashes.add(record.archive_record_hash)
        _validate_archive_record(record)
        _validate_replay_semantics(record.replay_result)
        rows.append((_parse_cycle_utc(record.cycle_as_of), record))

    rows.sort(key=lambda pair: pair[0])
    for left, right in zip(rows, rows[1:], strict=False):
        if left[0] == right[0]:
            raise ValueError("ambiguous cohort cycle")

    return tuple(record for _, record in rows)


def _cohort_input_hash(
    records: tuple[ReplayArchiveRecord, ...],
    horizons: tuple[int, ...],
) -> str:
    return canonical_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "evaluation_scope": EVALUATION_SCOPE,
            "horizons": list(horizons),
            "archive_record_hashes": [
                item.archive_record_hash for item in records
            ],
        }
    )


def _cohort_result_hash(
    *,
    horizons: tuple[int, ...],
    records: tuple[ReplayArchiveRecord, ...],
    transitions: tuple[ReplayCohortTransition, ...],
    summaries: tuple[ReplayCohortSummary, ...],
    input_hash: str,
) -> str:
    return canonical_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "evaluation_scope": EVALUATION_SCOPE,
            "horizons": list(horizons),
            "cycles": [item.cycle_as_of for item in records],
            "archive_record_hashes": [
                item.archive_record_hash for item in records
            ],
            "transitions": [asdict(item) for item in transitions],
            "summaries": [asdict(item) for item in summaries],
            "limitations": list(LIMITATIONS),
            "input_hash": input_hash,
        }
    )


def evaluate_replay_cohort(
    records: Sequence[ReplayArchiveRecord],
    horizons: Sequence[int] = (1, 3, 5),
) -> ReplayCohortResult:
    normalized_horizons = _normalize_horizons(horizons)
    normalized_records = _normalize_records(records)
    input_hash = _cohort_input_hash(
        normalized_records,
        normalized_horizons,
    )
    transitions: tuple[ReplayCohortTransition, ...] = ()
    summaries: tuple[ReplayCohortSummary, ...] = ()
    result_hash = _cohort_result_hash(
        horizons=normalized_horizons,
        records=normalized_records,
        transitions=transitions,
        summaries=summaries,
        input_hash=input_hash,
    )
    return ReplayCohortResult(
        schema_version=SCHEMA_VERSION,
        evaluation_scope=EVALUATION_SCOPE,
        horizons=normalized_horizons,
        cycles=tuple(
            item.cycle_as_of for item in normalized_records
        ),
        archive_record_hashes=tuple(
            item.archive_record_hash for item in normalized_records
        ),
        transitions=transitions,
        summaries=summaries,
        limitations=LIMITATIONS,
        input_hash=input_hash,
        result_hash=result_hash,
    )
