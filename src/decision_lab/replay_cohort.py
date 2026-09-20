from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from itertools import pairwise
from statistics import mean

from .ledger import canonical_hash
from .replay import ReplayCycleResult, ReplayStatus, ReplayThemeRecord
from .replay_archive import ReplayArchiveRecord, build_replay_archive_record
from .research_budget import ResearchTier
from .scanner import SupportDirection

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
    FORCED_REVIEW_UNREGISTERED = "FORCED_REVIEW_UNREGISTERED"


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

    for item in result.theme_records:
        _routing_intent(item)
        _independent_evidence_state(result, item.theme_id)


def _independent_evidence_state(
    result: ReplayCycleResult,
    theme_id: str,
) -> IndependentEvidenceState:
    grouped: dict[str, list[object]] = {}
    for observation in result.combined_observations:
        if observation.theme_id != theme_id:
            continue
        grouped.setdefault(observation.source_ref, []).append(observation)

    support_refs: list[str] = []
    contradiction_refs: list[str] = []
    neutral_refs: list[str] = []

    for source_ref, rows in grouped.items():
        metadata = {
            (row.source_type, row.is_independent)
            for row in rows
        }
        if len(metadata) != 1:
            raise ValueError("conflicting cohort source metadata")
        if not rows[0].is_independent:
            continue

        directions = {row.support_direction for row in rows}
        if SupportDirection.CONTRADICTING in directions:
            contradiction_refs.append(source_ref)
        elif SupportDirection.SUPPORTING in directions:
            support_refs.append(source_ref)
        else:
            neutral_refs.append(source_ref)

    support_refs.sort()
    contradiction_refs.sort()
    neutral_refs.sort()
    independent_count = (
        len(support_refs)
        + len(contradiction_refs)
        + len(neutral_refs)
    )

    if independent_count == 0:
        evidence_class = EvidenceClass.NO_INDEPENDENT
    elif support_refs and contradiction_refs:
        evidence_class = EvidenceClass.MIXED
    elif contradiction_refs:
        evidence_class = EvidenceClass.CONTRADICTION_PRESENT
    elif support_refs:
        evidence_class = EvidenceClass.SUPPORT_ONLY
    else:
        evidence_class = EvidenceClass.NEUTRAL_ONLY

    return IndependentEvidenceState(
        evidence_class=evidence_class,
        independent_source_count=independent_count,
        supporting_source_count=len(support_refs),
        contradicting_source_count=len(contradiction_refs),
        neutral_source_count=len(neutral_refs),
        supporting_source_refs=tuple(support_refs),
        contradicting_source_refs=tuple(contradiction_refs),
        neutral_source_refs=tuple(neutral_refs),
    )


def _routing_intent(item: ReplayThemeRecord) -> RoutingIntent:
    if item.replay_status is ReplayStatus.NO_OBSERVATION:
        return RoutingIntent.NO_OBSERVATION

    scan = item.scan_result
    allocation = item.allocation
    if scan is None or allocation is None:
        raise ValueError("inconsistent replay theme record")
    if scan.forced_review != allocation.forced_review:
        raise ValueError("forced-review flag mismatch")

    exhausted = (
        "forced review capacity exhausted"
        in allocation.allocation_reasons
    )

    if scan.forced_review:
        if (
            not item.registered
            and allocation.tier is ResearchTier.SCAN_ONLY
            and "theme not registered" in allocation.allocation_reasons
            and not exhausted
        ):
            return RoutingIntent.FORCED_REVIEW_UNREGISTERED
        if (
            allocation.tier is ResearchTier.FULL_DECISION_RESEARCH
            and not exhausted
        ):
            return RoutingIntent.FORCED_FULL_REVIEW
        if (
            allocation.tier is ResearchTier.SCAN_ONLY
            and exhausted
        ):
            return RoutingIntent.FORCED_REVIEW_CAPACITY_MISSED
        raise ValueError("unsupported forced-review allocation state")

    if exhausted:
        raise ValueError("unsupported forced-review allocation state")
    if allocation.tier is ResearchTier.FULL_DECISION_RESEARCH:
        return RoutingIntent.ORDINARY_FULL_RESEARCH
    if allocation.tier is ResearchTier.THEME_RESEARCH:
        return RoutingIntent.ORDINARY_THEME_RESEARCH
    if allocation.tier is ResearchTier.SCAN_ONLY:
        return RoutingIntent.SCAN_ONLY
    raise ValueError("unsupported forced-review allocation state")


_TIER_RANK = {
    ResearchTier.SCAN_ONLY: 0,
    ResearchTier.THEME_RESEARCH: 1,
    ResearchTier.FULL_DECISION_RESEARCH: 2,
}


def _contradiction_transition(
    source: IndependentEvidenceState,
    future: IndependentEvidenceState | None,
    presence: FuturePresence,
) -> ContradictionTransition:
    if (
        presence is not FuturePresence.PRESENT
        or future is None
        or source.independent_source_count == 0
        or future.independent_source_count == 0
    ):
        return ContradictionTransition.UNASSESSED

    source_has = source.contradicting_source_count > 0
    future_has = future.contradicting_source_count > 0
    if not source_has and future_has:
        return ContradictionTransition.EMERGED
    if source_has and future_has:
        return ContradictionTransition.PERSISTED
    if source_has and not future_has:
        return ContradictionTransition.RESOLVED
    return ContradictionTransition.ABSENT


def _tier_transition(
    source: ResearchTier | None,
    future: ResearchTier | None,
) -> TierTransition:
    if source is None or future is None:
        return TierTransition.UNASSESSED
    if source is future:
        return TierTransition.SAME
    if _TIER_RANK[future] > _TIER_RANK[source]:
        return TierTransition.ESCALATED
    return TierTransition.DEESCALATED


def _delta(source, future):
    if source is None or future is None:
        return None
    return future - source


def _system_fields(item: ReplayThemeRecord) -> dict[str, object]:
    scan = item.scan_result
    allocation = item.allocation
    return {
        "scanner_config_hash": None if scan is None else scan.config_hash,
        "priority": None if scan is None else scan.research_priority,
        "confidence": None if scan is None else scan.evidence_confidence,
        "novelty": None if scan is None else scan.novelty_score,
        "lifecycle": None if scan is None else scan.lifecycle_recommendation,
        "forced_review": None if scan is None else scan.forced_review,
        "tier": None if allocation is None else allocation.tier,
    }


def _build_transition(
    *,
    source_index: int,
    source_record: ReplayArchiveRecord,
    future_index: int | None,
    future_record: ReplayArchiveRecord | None,
    horizon: int,
    source_theme_record: ReplayThemeRecord,
) -> ReplayCohortTransition:
    theme_id = source_theme_record.theme_id
    source_evidence = _independent_evidence_state(
        source_record.replay_result,
        theme_id,
    )
    source_system = _system_fields(source_theme_record)
    routing_intent = _routing_intent(source_theme_record)

    future_theme_record = None
    if future_record is None:
        future_presence = FuturePresence.RIGHT_CENSORED
    else:
        future_by_theme = {
            item.theme_id: item
            for item in future_record.replay_result.theme_records
        }
        future_theme_record = future_by_theme.get(theme_id)
        future_presence = (
            FuturePresence.NOT_PRESENT
            if future_theme_record is None
            else FuturePresence.PRESENT
        )

    future_evidence = (
        None
        if future_theme_record is None
        else _independent_evidence_state(
            future_record.replay_result,
            theme_id,
        )
    )
    future_system = (
        None
        if future_theme_record is None
        else _system_fields(future_theme_record)
    )

    if (
        future_evidence is not None
        and source_evidence.independent_source_count > 0
        and future_evidence.independent_source_count > 0
    ):
        evidence_class_changed = (
            source_evidence.evidence_class
            is not future_evidence.evidence_class
        )
    else:
        evidence_class_changed = None

    support_delta = (
        None
        if future_presence is not FuturePresence.PRESENT
        else (
            future_evidence.supporting_source_count
            - source_evidence.supporting_source_count
        )
    )
    contradiction_delta = (
        None
        if future_presence is not FuturePresence.PRESENT
        else (
            future_evidence.contradicting_source_count
            - source_evidence.contradicting_source_count
        )
    )

    source_scanner_hash = source_system["scanner_config_hash"]
    future_scanner_hash = (
        None
        if future_system is None
        else future_system["scanner_config_hash"]
    )
    scanner_config_changed = (
        None
        if source_scanner_hash is None or future_scanner_hash is None
        else source_scanner_hash != future_scanner_hash
    )

    source_tier = source_system["tier"]
    future_tier = None if future_system is None else future_system["tier"]

    return ReplayCohortTransition(
        source_cycle_index=source_index,
        future_cycle_index=future_index,
        source_cycle_as_of=source_record.cycle_as_of,
        future_cycle_as_of=(
            None if future_record is None else future_record.cycle_as_of
        ),
        horizon_cycles=horizon,
        source_archive_record_hash=source_record.archive_record_hash,
        future_archive_record_hash=(
            None
            if future_record is None
            else future_record.archive_record_hash
        ),
        theme_id=theme_id,
        routing_intent=routing_intent,
        source_registered=source_theme_record.registered,
        future_presence=future_presence,
        future_registered=(
            None
            if future_theme_record is None
            else future_theme_record.registered
        ),
        source_evidence_state=source_evidence,
        future_evidence_state=future_evidence,
        support_delta=support_delta,
        contradiction_delta=contradiction_delta,
        contradiction_transition=_contradiction_transition(
            source_evidence,
            future_evidence,
            future_presence,
        ),
        evidence_class_changed=evidence_class_changed,
        source_replay_status=source_theme_record.replay_status,
        future_replay_status=(
            None
            if future_theme_record is None
            else future_theme_record.replay_status
        ),
        source_scanner_config_hash=source_scanner_hash,
        future_scanner_config_hash=future_scanner_hash,
        scanner_config_changed=scanner_config_changed,
        source_priority=source_system["priority"],
        future_priority=(
            None if future_system is None else future_system["priority"]
        ),
        priority_delta=_delta(
            source_system["priority"],
            None if future_system is None else future_system["priority"],
        ),
        source_confidence=source_system["confidence"],
        future_confidence=(
            None if future_system is None else future_system["confidence"]
        ),
        confidence_delta=_delta(
            source_system["confidence"],
            None if future_system is None else future_system["confidence"],
        ),
        source_novelty=source_system["novelty"],
        future_novelty=(
            None if future_system is None else future_system["novelty"]
        ),
        novelty_delta=_delta(
            source_system["novelty"],
            None if future_system is None else future_system["novelty"],
        ),
        source_lifecycle=source_system["lifecycle"],
        future_lifecycle=(
            None if future_system is None else future_system["lifecycle"]
        ),
        source_forced_review=source_system["forced_review"],
        future_forced_review=(
            None if future_system is None else future_system["forced_review"]
        ),
        source_tier=source_tier,
        future_tier=future_tier,
        tier_transition=_tier_transition(source_tier, future_tier),
    )


def _build_transitions(
    records: tuple[ReplayArchiveRecord, ...],
    horizons: tuple[int, ...],
) -> tuple[ReplayCohortTransition, ...]:
    rows: list[ReplayCohortTransition] = []
    for source_index, source_record in enumerate(records):
        source_records = sorted(
            source_record.replay_result.theme_records,
            key=lambda item: item.theme_id,
        )
        for horizon in horizons:
            candidate_future_index = source_index + horizon
            future_record = (
                None
                if candidate_future_index >= len(records)
                else records[candidate_future_index]
            )
            for theme_record in source_records:
                rows.append(
                    _build_transition(
                        source_index=source_index,
                        source_record=source_record,
                        future_index=(
                            None
                            if future_record is None
                            else candidate_future_index
                        ),
                        future_record=future_record,
                        horizon=horizon,
                        source_theme_record=theme_record,
                    )
                )
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                item.source_cycle_index,
                item.horizon_cycles,
                item.theme_id,
            ),
        )
    )


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
    for left, right in pairwise(rows):
        if left[0] == right[0]:
            raise ValueError("ambiguous cohort cycle")

    return tuple(record for _, record in rows)


def _mean_or_none(values: Sequence[float]) -> float | None:
    return None if not values else mean(values)


def _build_summary(
    routing_intent: RoutingIntent,
    horizon: int,
    rows: Sequence[ReplayCohortTransition],
) -> ReplayCohortSummary:
    contradiction_counts = {
        value: sum(
            item.contradiction_transition is value
            for item in rows
        )
        for value in ContradictionTransition
    }
    tier_counts = {
        value: sum(
            item.tier_transition is value
            for item in rows
        )
        for value in TierTransition
    }

    forced_unassessed = 0
    forced_inactive = 0
    forced_emerged = 0
    forced_persisted = 0
    forced_resolved = 0
    scanner_unassessed = 0
    scanner_same = 0
    scanner_changed = 0

    for item in rows:
        if (
            item.source_forced_review is None
            or item.future_forced_review is None
        ):
            forced_unassessed += 1
        elif not item.source_forced_review and not item.future_forced_review:
            forced_inactive += 1
        elif not item.source_forced_review and item.future_forced_review:
            forced_emerged += 1
        elif item.source_forced_review and item.future_forced_review:
            forced_persisted += 1
        else:
            forced_resolved += 1

        if item.scanner_config_changed is None:
            scanner_unassessed += 1
        elif item.scanner_config_changed:
            scanner_changed += 1
        else:
            scanner_same += 1

    priority = [
        item.priority_delta
        for item in rows
        if item.priority_delta is not None
    ]
    confidence = [
        item.confidence_delta
        for item in rows
        if item.confidence_delta is not None
    ]
    novelty = [
        item.novelty_delta
        for item in rows
        if item.novelty_delta is not None
    ]

    return ReplayCohortSummary(
        routing_intent=routing_intent,
        horizon_cycles=horizon,
        source_n=len(rows),
        future_cycle_available_n=sum(
            item.future_presence is not FuturePresence.RIGHT_CENSORED
            for item in rows
        ),
        right_censored_n=sum(
            item.future_presence is FuturePresence.RIGHT_CENSORED
            for item in rows
        ),
        future_present_n=sum(
            item.future_presence is FuturePresence.PRESENT
            for item in rows
        ),
        future_not_present_n=sum(
            item.future_presence is FuturePresence.NOT_PRESENT
            for item in rows
        ),
        future_independent_evidence_n=sum(
            item.future_evidence_state is not None
            and item.future_evidence_state.independent_source_count > 0
            for item in rows
        ),
        contradiction_unassessed_n=contradiction_counts[
            ContradictionTransition.UNASSESSED
        ],
        contradiction_absent_n=contradiction_counts[
            ContradictionTransition.ABSENT
        ],
        contradiction_emerged_n=contradiction_counts[
            ContradictionTransition.EMERGED
        ],
        contradiction_persisted_n=contradiction_counts[
            ContradictionTransition.PERSISTED
        ],
        contradiction_resolved_n=contradiction_counts[
            ContradictionTransition.RESOLVED
        ],
        source_independent_evidence_n=sum(
            item.source_evidence_state.independent_source_count > 0
            for item in rows
        ),
        evidence_class_comparable_n=sum(
            item.evidence_class_changed is not None
            for item in rows
        ),
        evidence_class_changed_n=sum(
            item.evidence_class_changed is True
            for item in rows
        ),
        tier_unassessed_n=tier_counts[TierTransition.UNASSESSED],
        tier_same_n=tier_counts[TierTransition.SAME],
        tier_escalated_n=tier_counts[TierTransition.ESCALATED],
        tier_deescalated_n=tier_counts[TierTransition.DEESCALATED],
        forced_review_unassessed_n=forced_unassessed,
        forced_review_inactive_n=forced_inactive,
        forced_review_emerged_n=forced_emerged,
        forced_review_persisted_n=forced_persisted,
        forced_review_resolved_n=forced_resolved,
        scanner_config_unassessed_n=scanner_unassessed,
        scanner_config_same_n=scanner_same,
        scanner_config_changed_n=scanner_changed,
        priority_delta_n=len(priority),
        mean_priority_delta=_mean_or_none(priority),
        confidence_delta_n=len(confidence),
        mean_confidence_delta=_mean_or_none(confidence),
        novelty_delta_n=len(novelty),
        mean_novelty_delta=_mean_or_none(novelty),
    )


def _build_summaries(
    transitions: tuple[ReplayCohortTransition, ...],
) -> tuple[ReplayCohortSummary, ...]:
    grouped: dict[
        tuple[RoutingIntent, int],
        list[ReplayCohortTransition],
    ] = {}
    for item in transitions:
        grouped.setdefault(
            (item.routing_intent, item.horizon_cycles),
            [],
        ).append(item)

    summaries = [
        _build_summary(intent, horizon, rows)
        for (intent, horizon), rows in grouped.items()
    ]
    return tuple(
        sorted(
            summaries,
            key=lambda item: (
                item.horizon_cycles,
                item.routing_intent.value,
            ),
        )
    )


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
    transitions = _build_transitions(
        normalized_records,
        normalized_horizons,
    )
    summaries = _build_summaries(transitions)
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
