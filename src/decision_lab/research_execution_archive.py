from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from .ledger import canonical_hash
from .replay_archive import ReplayArchiveRecord, build_replay_archive_record
from .replay_cohort import evaluate_replay_cohort
from .research_execution import (
    ResearchWorkOrder,
    ResearchWorkOrderPolicy,
    _CONTRADICTION_QUESTIONS,
    _build_requirements,
    _normalize_policy,
    _validate_work_order_hash,
)

SCHEMA_VERSION = "0.1"
PRODUCER = "theme-radar-decision-lab/research-execution-archive@0.1"
WORK_ORDER_CONTENT_TYPE = "research_work_order"
DOSSIER_CONTENT_TYPE = "research_dossier"


class ResearchArchiveDestinationVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"


@dataclass(frozen=True)
class ResearchArchiveWriteResult:
    path: Path
    created: bool
    content_hash: str
    archive_record_hash: str


@dataclass(frozen=True)
class ResearchWorkOrderArchiveRecord:
    schema_version: str
    content_type: str
    producer: str
    source_cycle_as_of: str
    source_replay_archive_record_hash: str
    source_replay_result_hash: str
    work_order_hash: str
    work_order_policy: ResearchWorkOrderPolicy
    work_order: ResearchWorkOrder
    archive_record_hash: str


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    if "T" not in value and " " not in value:
        dt = dt.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )
    return dt


def _cycle_date(value: str) -> str:
    return _parse_utc(value).date().isoformat()


def _validate_sha256(value: str, *, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"invalid {field_name}")


def _validate_work_order_policy(
    order: ResearchWorkOrder,
    policy: ResearchWorkOrderPolicy,
) -> ResearchWorkOrderPolicy:
    try:
        normalized = _normalize_policy(policy)
        _validate_work_order_hash(order)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid research work order") from exc

    if (
        order.targets
        != tuple(sorted(order.targets, key=lambda item: item.ticker))
        or any(
            not target.ticker
            or target.ticker != target.ticker.upper()
            for target in order.targets
        )
        or (
            order.source_forced_review
            and order.contradiction_questions
            != _CONTRADICTION_QUESTIONS
        )
        or (
            not order.source_forced_review
            and order.contradiction_questions
        )
    ):
        raise ValueError("invalid research work order")

    if canonical_hash(asdict(normalized)) != order.policy_hash:
        raise ValueError("research work order policy mismatch")
    if (
        normalized.minimum_independent_sources
        != order.minimum_independent_sources
        or normalized.minimum_independent_sources_per_company
        != order.minimum_independent_sources_per_company
    ):
        raise ValueError("research work order policy mismatch")

    try:
        expected_requirements = _build_requirements(
            mode=order.research_mode,
            targets=order.targets,
            adapter_name=order.evidence_adapter,
            policy=normalized,
        )
    except (TypeError, ValueError, AssertionError) as exc:
        raise ValueError("research work order policy mismatch") from exc

    if expected_requirements != order.requirements:
        raise ValueError("research work order policy mismatch")
    return normalized


def _validate_source_replay(
    replay_archive: ReplayArchiveRecord,
) -> None:
    try:
        rebuilt = build_replay_archive_record(
            replay_archive.replay_result
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "invalid source replay archive record"
        ) from exc
    if rebuilt != replay_archive:
        raise ValueError("invalid source replay archive record")


def _validate_replay_work_order_lineage(
    replay_archive: ReplayArchiveRecord,
    order: ResearchWorkOrder,
) -> None:
    if (
        order.source_archive_record_hash
        != replay_archive.archive_record_hash
        or order.source_replay_result_hash
        != replay_archive.replay_result_hash
        or order.source_cycle_as_of
        != replay_archive.cycle_as_of
    ):
        raise ValueError(
            "research work order replay lineage mismatch"
        )

    cohort = evaluate_replay_cohort(
        (replay_archive,),
        horizons=(1,),
    )
    matches = [
        item
        for item in cohort.transitions
        if item.theme_id == order.theme_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "research work order replay lineage mismatch"
        )
    transition = matches[0]
    if (
        transition.routing_intent
        is not order.source_routing_intent
        or transition.source_registered
        != order.source_registered
        or transition.source_tier
        is not order.source_allocated_tier
        or transition.source_forced_review
        != order.source_forced_review
    ):
        raise ValueError(
            "research work order replay lineage mismatch"
        )


def _work_order_archive_payload_without_hash(
    record: ResearchWorkOrderArchiveRecord,
) -> dict[str, object]:
    payload = asdict(record)
    payload.pop("archive_record_hash")
    return payload


def _validate_work_order_archive_record(
    record: ResearchWorkOrderArchiveRecord,
) -> None:
    if (
        record.schema_version != SCHEMA_VERSION
        or record.content_type != WORK_ORDER_CONTENT_TYPE
        or record.producer != PRODUCER
    ):
        raise ValueError(
            "unsupported research work-order archive contract"
        )

    for field_name, value in (
        (
            "source replay archive record hash",
            record.source_replay_archive_record_hash,
        ),
        (
            "source replay result hash",
            record.source_replay_result_hash,
        ),
        ("work order hash", record.work_order_hash),
        (
            "research work-order archive hash",
            record.archive_record_hash,
        ),
    ):
        _validate_sha256(value, field_name=field_name)

    normalized_policy = _validate_work_order_policy(
        record.work_order,
        record.work_order_policy,
    )
    if normalized_policy != record.work_order_policy:
        raise ValueError("research work order policy mismatch")

    if (
        record.source_cycle_as_of
        != record.work_order.source_cycle_as_of
        or record.source_replay_archive_record_hash
        != record.work_order.source_archive_record_hash
        or record.source_replay_result_hash
        != record.work_order.source_replay_result_hash
        or record.work_order_hash
        != record.work_order.work_order_hash
    ):
        raise ValueError(
            "research work-order archive nested identity mismatch"
        )

    expected = canonical_hash(
        _work_order_archive_payload_without_hash(record)
    )
    if expected != record.archive_record_hash:
        raise ValueError(
            "research work-order archive hash mismatch"
        )


def build_research_work_order_archive_record(
    replay_archive: ReplayArchiveRecord,
    work_order: ResearchWorkOrder,
    *,
    work_order_policy: ResearchWorkOrderPolicy,
) -> ResearchWorkOrderArchiveRecord:
    _validate_source_replay(replay_archive)
    normalized_policy = _validate_work_order_policy(
        work_order,
        work_order_policy,
    )
    _validate_replay_work_order_lineage(
        replay_archive,
        work_order,
    )

    seed = ResearchWorkOrderArchiveRecord(
        schema_version=SCHEMA_VERSION,
        content_type=WORK_ORDER_CONTENT_TYPE,
        producer=PRODUCER,
        source_cycle_as_of=work_order.source_cycle_as_of,
        source_replay_archive_record_hash=(
            replay_archive.archive_record_hash
        ),
        source_replay_result_hash=(
            replay_archive.replay_result_hash
        ),
        work_order_hash=work_order.work_order_hash,
        work_order_policy=normalized_policy,
        work_order=work_order,
        archive_record_hash="0" * 64,
    )
    record = replace(
        seed,
        archive_record_hash=canonical_hash(
            _work_order_archive_payload_without_hash(seed)
        ),
    )
    _validate_work_order_archive_record(record)
    return record


def research_work_order_archive_path(
    record: ResearchWorkOrderArchiveRecord,
    archive_root: str | Path,
) -> Path:
    return (
        Path(archive_root)
        / "work_orders"
        / _cycle_date(record.source_cycle_as_of)
        / f"{record.work_order_hash}.json"
    )
