from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
import re

from .ledger import canonical_hash
from .replay import ReplayCycleResult

SCHEMA_VERSION = "0.1"
CONTENT_TYPE = "replay_cycle_result"
PRODUCER = "theme-radar-decision-lab/replay-archive@0.1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ArchiveDestinationVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"


@dataclass(frozen=True)
class ReplayArchiveRecord:
    schema_version: str
    content_type: str
    producer: str
    cycle_as_of: str
    replay_input_hash: str
    replay_result_hash: str
    replay_result: ReplayCycleResult
    archive_record_hash: str


@dataclass(frozen=True)
class ReplayArchiveWriteResult:
    path: Path
    created: bool
    replay_result_hash: str
    archive_record_hash: str


def _parse_cycle_date(value: str) -> date:
    if "T" not in value and " " not in value:
        return date.fromisoformat(value)
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).date()


def _validate_sha256_hex(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be lowercase sha256 hex")


def _replay_result_payload_without_hash(
    result: ReplayCycleResult,
) -> dict[str, object]:
    return {
        "cycle_as_of": result.cycle_as_of,
        "input_hash": result.input_hash,
        "market_batches": [asdict(item) for item in result.market_batches],
        "combined_observations": [
            asdict(item) for item in result.combined_observations
        ],
        "scan_results": [asdict(item) for item in result.scan_results],
        "allocations": [asdict(item) for item in result.allocations],
        "theme_records": [asdict(item) for item in result.theme_records],
    }


def _recompute_replay_result_hash(result: ReplayCycleResult) -> str:
    return canonical_hash(_replay_result_payload_without_hash(result))


def _archive_payload_without_hash(
    record: ReplayArchiveRecord,
) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "content_type": record.content_type,
        "producer": record.producer,
        "cycle_as_of": record.cycle_as_of,
        "replay_input_hash": record.replay_input_hash,
        "replay_result_hash": record.replay_result_hash,
        "replay_result": asdict(record.replay_result),
    }


def _validate_archive_record(record: ReplayArchiveRecord) -> None:
    if record.schema_version != SCHEMA_VERSION:
        raise ValueError("unsupported replay archive schema_version")
    if record.content_type != CONTENT_TYPE:
        raise ValueError("unsupported replay archive content_type")
    if record.producer != PRODUCER:
        raise ValueError("unsupported replay archive producer")

    _validate_sha256_hex(
        record.replay_input_hash,
        field_name="replay input hash",
    )
    _validate_sha256_hex(
        record.replay_result_hash,
        field_name="replay result hash",
    )
    _validate_sha256_hex(
        record.replay_result.input_hash,
        field_name="nested replay input hash",
    )
    _validate_sha256_hex(
        record.replay_result.result_hash,
        field_name="nested replay result hash",
    )
    _validate_sha256_hex(
        record.archive_record_hash,
        field_name="archive record hash",
    )

    if record.cycle_as_of != record.replay_result.cycle_as_of:
        raise ValueError("archive cycle_as_of mismatch")
    if record.replay_input_hash != record.replay_result.input_hash:
        raise ValueError("archive replay input hash mismatch")
    if record.replay_result_hash != record.replay_result.result_hash:
        raise ValueError("archive replay result hash mismatch")

    recomputed_result = _recompute_replay_result_hash(
        record.replay_result
    )
    if recomputed_result != record.replay_result.result_hash:
        raise ValueError("replay result hash mismatch")

    recomputed_archive = canonical_hash(
        _archive_payload_without_hash(record)
    )
    if recomputed_archive != record.archive_record_hash:
        raise ValueError("archive record hash mismatch")


def build_replay_archive_record(
    replay_result: ReplayCycleResult,
) -> ReplayArchiveRecord:
    _validate_sha256_hex(
        replay_result.input_hash,
        field_name="replay input hash",
    )
    _validate_sha256_hex(
        replay_result.result_hash,
        field_name="replay result hash",
    )
    if _recompute_replay_result_hash(replay_result) != replay_result.result_hash:
        raise ValueError("replay result hash mismatch")

    seed = ReplayArchiveRecord(
        schema_version=SCHEMA_VERSION,
        content_type=CONTENT_TYPE,
        producer=PRODUCER,
        cycle_as_of=replay_result.cycle_as_of,
        replay_input_hash=replay_result.input_hash,
        replay_result_hash=replay_result.result_hash,
        replay_result=replay_result,
        archive_record_hash="0" * 64,
    )
    archive_hash = canonical_hash(_archive_payload_without_hash(seed))
    record = ReplayArchiveRecord(
        schema_version=seed.schema_version,
        content_type=seed.content_type,
        producer=seed.producer,
        cycle_as_of=seed.cycle_as_of,
        replay_input_hash=seed.replay_input_hash,
        replay_result_hash=seed.replay_result_hash,
        replay_result=seed.replay_result,
        archive_record_hash=archive_hash,
    )
    _validate_archive_record(record)
    return record


def replay_archive_path(
    record: ReplayArchiveRecord,
    archive_root: str | Path,
) -> Path:
    _validate_sha256_hex(
        record.replay_result_hash,
        field_name="replay result hash",
    )
    cycle_date = _parse_cycle_date(record.cycle_as_of).isoformat()
    return (
        Path(archive_root)
        / cycle_date
        / f"{record.replay_result_hash}.json"
    )
