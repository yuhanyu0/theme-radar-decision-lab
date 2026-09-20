from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import Enum
import json
from math import isfinite
import os
from pathlib import Path
import re

from .ledger import canonical_hash
from .market_observation import (
    MarketObservationBatch,
    MarketObservationDiagnostics,
    MarketObservationMode,
    MarketObservationStatus,
)
from .replay import (
    ReplayCycleResult,
    ReplayStatus,
    ReplayThemeRecord,
)
from .research_budget import ResearchAllocation, ResearchTier
from .scanner import (
    SupportDirection,
    ThemeScanObservation,
    ThemeScanResult,
)

SCHEMA_VERSION = "0.1"
CONTENT_TYPE = "replay_cycle_result"
PRODUCER = "theme-radar-decision-lab/replay-archive@0.1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_ARCHIVE_FIELDS = {
    "schema_version",
    "content_type",
    "producer",
    "cycle_as_of",
    "replay_input_hash",
    "replay_result_hash",
    "replay_result",
    "archive_record_hash",
}

_REPLAY_RESULT_FIELDS = {
    "cycle_as_of",
    "market_batches",
    "combined_observations",
    "scan_results",
    "allocations",
    "theme_records",
    "input_hash",
    "result_hash",
}

_REPLAY_THEME_RECORD_FIELDS = {
    "theme_id",
    "registered",
    "market_batch",
    "scan_result",
    "allocation",
    "replay_status",
}

_MARKET_BATCH_FIELDS = {
    "theme_id",
    "cycle_as_of",
    "market_as_of",
    "observations",
    "diagnostics",
    "input_hash",
    "spec_hash",
    "config_hash",
}

_MARKET_DIAGNOSTIC_FIELDS = {
    "theme_id",
    "mode",
    "instrument",
    "benchmark",
    "market_as_of",
    "current_start",
    "current_end",
    "prior_start",
    "prior_end",
    "status",
    "reason",
    "current_return",
    "benchmark_current_return",
    "current_excess_return",
    "comparison_current_excess_return",
    "comparison_prior_excess_return",
    "novelty_abs_excess_change",
    "breadth",
    "persistence",
    "current_member_symbols",
    "stable_member_symbols",
    "current_member_count",
    "stable_member_count",
    "membership_changed",
    "support_direction",
    "relative_strength_signal",
    "breadth_signal",
    "persistence_signal",
    "novelty_signal",
    "universe_version",
    "package_version",
    "spec_version",
    "config_version",
    "input_hash",
    "spec_hash",
    "config_hash",
    "diagnostic_hash",
    "evidence_refs",
    "warnings",
}

_THEME_SCAN_OBSERVATION_FIELDS = {
    "theme_id",
    "as_of",
    "source_type",
    "source_ref",
    "discovery_signal",
    "structure_signal",
    "persistence_signal",
    "breadth_signal",
    "relative_strength_signal",
    "volatility_signal",
    "novelty_signal",
    "support_direction",
    "evidence_refs",
    "is_independent",
    "observed_or_inferred",
    "notes",
}

_THEME_SCAN_RESULT_FIELDS = {
    "theme_id",
    "as_of",
    "discovery_score",
    "structural_score",
    "persistence_score",
    "breadth_score",
    "relative_strength_score",
    "novelty_score",
    "evidence_confidence",
    "independent_support_count",
    "independent_contradiction_count",
    "lifecycle_recommendation",
    "research_priority",
    "forced_review",
    "forced_review_severity",
    "forced_review_reasons",
    "reasons",
    "evidence_refs",
    "config_hash",
    "registry_version",
    "prior_result_refs",
}

_RESEARCH_ALLOCATION_FIELDS = {
    "theme_id",
    "as_of",
    "tier",
    "scan_priority",
    "effective_priority",
    "scan_novelty_score",
    "forced_review",
    "allocation_reasons",
    "source_scan_result_hash",
}

_SOURCE_TYPES = {
    "market_data",
    "sec_filing",
    "company_ir",
    "official_macro",
    "industry_primary",
    "reputable_reporting",
    "radar_model_output",
    "derived_feature",
}


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


def _record_payload(record: ReplayArchiveRecord) -> dict[str, object]:
    return {
        **_archive_payload_without_hash(record),
        "archive_record_hash": record.archive_record_hash,
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


def _require_mapping(value, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a JSON object")
    return dict(value)


def _require_exact_fields(
    payload: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    actual = set(payload)
    missing = expected - actual
    extra = actual - expected
    if missing:
        raise ValueError(f"missing {label} fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"unexpected {label} fields: {sorted(extra)}")


def _require_list(value, *, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a JSON array")
    return value


def _require_str(value, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _require_optional_str(value, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name=field_name)


def _require_literal(
    value,
    *,
    field_name: str,
    allowed: set[str],
) -> str:
    text = _require_str(value, field_name=field_name)
    if text not in allowed:
        raise ValueError(f"invalid {field_name}")
    return text


def _require_number_or_none(value, *, field_name: str):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric or null")
    if not isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")
    return value


def _require_number(value, *, field_name: str) -> float | int:
    number = _require_number_or_none(value, field_name=field_name)
    if number is None:
        raise TypeError(f"{field_name} must be numeric")
    return number


def _require_int(value, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _require_bool(value, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _tuple_of_strings(value, *, field_name: str) -> tuple[str, ...]:
    items = _require_list(value, field_name=field_name)
    if not all(isinstance(item, str) for item in items):
        raise TypeError(f"{field_name} must contain strings")
    return tuple(items)


def _decode_theme_scan_observation(value) -> ThemeScanObservation:
    payload = _require_mapping(value, label="ThemeScanObservation")
    _require_exact_fields(
        payload,
        _THEME_SCAN_OBSERVATION_FIELDS,
        label="ThemeScanObservation",
    )
    source_type = _require_str(
        payload["source_type"],
        field_name="source_type",
    )
    if source_type not in _SOURCE_TYPES:
        raise ValueError("invalid ThemeScanObservation source_type")

    return ThemeScanObservation(
        theme_id=_require_str(payload["theme_id"], field_name="theme_id"),
        as_of=_require_str(payload["as_of"], field_name="as_of"),
        source_type=source_type,
        source_ref=_require_str(payload["source_ref"], field_name="source_ref"),
        discovery_signal=_require_number_or_none(
            payload["discovery_signal"],
            field_name="discovery_signal",
        ),
        structure_signal=_require_number_or_none(
            payload["structure_signal"],
            field_name="structure_signal",
        ),
        persistence_signal=_require_number_or_none(
            payload["persistence_signal"],
            field_name="persistence_signal",
        ),
        breadth_signal=_require_number_or_none(
            payload["breadth_signal"],
            field_name="breadth_signal",
        ),
        relative_strength_signal=_require_number_or_none(
            payload["relative_strength_signal"],
            field_name="relative_strength_signal",
        ),
        volatility_signal=_require_number_or_none(
            payload["volatility_signal"],
            field_name="volatility_signal",
        ),
        novelty_signal=_require_number_or_none(
            payload["novelty_signal"],
            field_name="novelty_signal",
        ),
        support_direction=SupportDirection(
            _require_str(
                payload["support_direction"],
                field_name="support_direction",
            )
        ),
        evidence_refs=_tuple_of_strings(
            payload["evidence_refs"],
            field_name="evidence_refs",
        ),
        is_independent=_require_bool(
            payload["is_independent"],
            field_name="is_independent",
        ),
        observed_or_inferred=_require_literal(
            payload["observed_or_inferred"],
            field_name="observed_or_inferred",
            allowed={"observed", "inferred"},
        ),
        notes=_require_optional_str(payload["notes"], field_name="notes"),
    )


def _decode_market_diagnostic(value) -> MarketObservationDiagnostics:
    payload = _require_mapping(value, label="MarketObservationDiagnostics")
    _require_exact_fields(
        payload,
        _MARKET_DIAGNOSTIC_FIELDS,
        label="MarketObservationDiagnostics",
    )
    return MarketObservationDiagnostics(
        theme_id=_require_str(payload["theme_id"], field_name="theme_id"),
        mode=MarketObservationMode(
            _require_str(payload["mode"], field_name="mode")
        ),
        instrument=_require_str(
            payload["instrument"],
            field_name="instrument",
        ),
        benchmark=_require_str(
            payload["benchmark"],
            field_name="benchmark",
        ),
        market_as_of=_require_optional_str(
            payload["market_as_of"],
            field_name="market_as_of",
        ),
        current_start=_require_optional_str(
            payload["current_start"],
            field_name="current_start",
        ),
        current_end=_require_optional_str(
            payload["current_end"],
            field_name="current_end",
        ),
        prior_start=_require_optional_str(
            payload["prior_start"],
            field_name="prior_start",
        ),
        prior_end=_require_optional_str(
            payload["prior_end"],
            field_name="prior_end",
        ),
        status=MarketObservationStatus(
            _require_str(payload["status"], field_name="status")
        ),
        reason=_require_str(payload["reason"], field_name="reason"),
        current_return=_require_number_or_none(
            payload["current_return"],
            field_name="current_return",
        ),
        benchmark_current_return=_require_number_or_none(
            payload["benchmark_current_return"],
            field_name="benchmark_current_return",
        ),
        current_excess_return=_require_number_or_none(
            payload["current_excess_return"],
            field_name="current_excess_return",
        ),
        comparison_current_excess_return=_require_number_or_none(
            payload["comparison_current_excess_return"],
            field_name="comparison_current_excess_return",
        ),
        comparison_prior_excess_return=_require_number_or_none(
            payload["comparison_prior_excess_return"],
            field_name="comparison_prior_excess_return",
        ),
        novelty_abs_excess_change=_require_number_or_none(
            payload["novelty_abs_excess_change"],
            field_name="novelty_abs_excess_change",
        ),
        breadth=_require_number_or_none(
            payload["breadth"],
            field_name="breadth",
        ),
        persistence=_require_number_or_none(
            payload["persistence"],
            field_name="persistence",
        ),
        current_member_symbols=_tuple_of_strings(
            payload["current_member_symbols"],
            field_name="current_member_symbols",
        ),
        stable_member_symbols=_tuple_of_strings(
            payload["stable_member_symbols"],
            field_name="stable_member_symbols",
        ),
        current_member_count=_require_int(
            payload["current_member_count"],
            field_name="current_member_count",
        ),
        stable_member_count=_require_int(
            payload["stable_member_count"],
            field_name="stable_member_count",
        ),
        membership_changed=_require_bool(
            payload["membership_changed"],
            field_name="membership_changed",
        ),
        support_direction=SupportDirection(
            _require_str(
                payload["support_direction"],
                field_name="support_direction",
            )
        ),
        relative_strength_signal=_require_number_or_none(
            payload["relative_strength_signal"],
            field_name="relative_strength_signal",
        ),
        breadth_signal=_require_number_or_none(
            payload["breadth_signal"],
            field_name="breadth_signal",
        ),
        persistence_signal=_require_number_or_none(
            payload["persistence_signal"],
            field_name="persistence_signal",
        ),
        novelty_signal=_require_number_or_none(
            payload["novelty_signal"],
            field_name="novelty_signal",
        ),
        universe_version=_require_str(
            payload["universe_version"],
            field_name="universe_version",
        ),
        package_version=_require_str(
            payload["package_version"],
            field_name="package_version",
        ),
        spec_version=_require_str(
            payload["spec_version"],
            field_name="spec_version",
        ),
        config_version=_require_str(
            payload["config_version"],
            field_name="config_version",
        ),
        input_hash=_require_str(
            payload["input_hash"],
            field_name="input_hash",
        ),
        spec_hash=_require_str(
            payload["spec_hash"],
            field_name="spec_hash",
        ),
        config_hash=_require_str(
            payload["config_hash"],
            field_name="config_hash",
        ),
        diagnostic_hash=_require_optional_str(
            payload["diagnostic_hash"],
            field_name="diagnostic_hash",
        ),
        evidence_refs=_tuple_of_strings(
            payload["evidence_refs"],
            field_name="evidence_refs",
        ),
        warnings=_tuple_of_strings(
            payload["warnings"],
            field_name="warnings",
        ),
    )


def _decode_market_batch(value) -> MarketObservationBatch:
    payload = _require_mapping(value, label="MarketObservationBatch")
    _require_exact_fields(
        payload,
        _MARKET_BATCH_FIELDS,
        label="MarketObservationBatch",
    )
    return MarketObservationBatch(
        theme_id=_require_str(payload["theme_id"], field_name="theme_id"),
        cycle_as_of=_require_str(
            payload["cycle_as_of"],
            field_name="cycle_as_of",
        ),
        market_as_of=_require_optional_str(
            payload["market_as_of"],
            field_name="market_as_of",
        ),
        observations=tuple(
            _decode_theme_scan_observation(item)
            for item in _require_list(
                payload["observations"],
                field_name="observations",
            )
        ),
        diagnostics=tuple(
            _decode_market_diagnostic(item)
            for item in _require_list(
                payload["diagnostics"],
                field_name="diagnostics",
            )
        ),
        input_hash=_require_str(
            payload["input_hash"],
            field_name="input_hash",
        ),
        spec_hash=_require_str(
            payload["spec_hash"],
            field_name="spec_hash",
        ),
        config_hash=_require_str(
            payload["config_hash"],
            field_name="config_hash",
        ),
    )


def _decode_scan_result(value) -> ThemeScanResult:
    payload = _require_mapping(value, label="ThemeScanResult")
    _require_exact_fields(
        payload,
        _THEME_SCAN_RESULT_FIELDS,
        label="ThemeScanResult",
    )
    return ThemeScanResult(
        theme_id=_require_str(payload["theme_id"], field_name="theme_id"),
        as_of=_require_str(payload["as_of"], field_name="as_of"),
        discovery_score=_require_number_or_none(
            payload["discovery_score"],
            field_name="discovery_score",
        ),
        structural_score=_require_number_or_none(
            payload["structural_score"],
            field_name="structural_score",
        ),
        persistence_score=_require_number_or_none(
            payload["persistence_score"],
            field_name="persistence_score",
        ),
        breadth_score=_require_number_or_none(
            payload["breadth_score"],
            field_name="breadth_score",
        ),
        relative_strength_score=_require_number_or_none(
            payload["relative_strength_score"],
            field_name="relative_strength_score",
        ),
        novelty_score=_require_number_or_none(
            payload["novelty_score"],
            field_name="novelty_score",
        ),
        evidence_confidence=_require_number(
            payload["evidence_confidence"],
            field_name="evidence_confidence",
        ),
        independent_support_count=_require_int(
            payload["independent_support_count"],
            field_name="independent_support_count",
        ),
        independent_contradiction_count=_require_int(
            payload["independent_contradiction_count"],
            field_name="independent_contradiction_count",
        ),
        lifecycle_recommendation=_require_str(
            payload["lifecycle_recommendation"],
            field_name="lifecycle_recommendation",
        ),
        research_priority=_require_number(
            payload["research_priority"],
            field_name="research_priority",
        ),
        forced_review=_require_bool(
            payload["forced_review"],
            field_name="forced_review",
        ),
        forced_review_severity=_require_int(
            payload["forced_review_severity"],
            field_name="forced_review_severity",
        ),
        forced_review_reasons=_tuple_of_strings(
            payload["forced_review_reasons"],
            field_name="forced_review_reasons",
        ),
        reasons=_tuple_of_strings(
            payload["reasons"],
            field_name="reasons",
        ),
        evidence_refs=_tuple_of_strings(
            payload["evidence_refs"],
            field_name="evidence_refs",
        ),
        config_hash=_require_str(
            payload["config_hash"],
            field_name="config_hash",
        ),
        registry_version=_require_optional_str(
            payload["registry_version"],
            field_name="registry_version",
        ),
        prior_result_refs=_tuple_of_strings(
            payload["prior_result_refs"],
            field_name="prior_result_refs",
        ),
    )


def _decode_allocation(value) -> ResearchAllocation:
    payload = _require_mapping(value, label="ResearchAllocation")
    _require_exact_fields(
        payload,
        _RESEARCH_ALLOCATION_FIELDS,
        label="ResearchAllocation",
    )
    return ResearchAllocation(
        theme_id=_require_str(payload["theme_id"], field_name="theme_id"),
        as_of=_require_str(payload["as_of"], field_name="as_of"),
        tier=ResearchTier(
            _require_str(payload["tier"], field_name="tier")
        ),
        scan_priority=_require_number(
            payload["scan_priority"],
            field_name="scan_priority",
        ),
        effective_priority=_require_number(
            payload["effective_priority"],
            field_name="effective_priority",
        ),
        scan_novelty_score=_require_number_or_none(
            payload["scan_novelty_score"],
            field_name="scan_novelty_score",
        ),
        forced_review=_require_bool(
            payload["forced_review"],
            field_name="forced_review",
        ),
        allocation_reasons=_tuple_of_strings(
            payload["allocation_reasons"],
            field_name="allocation_reasons",
        ),
        source_scan_result_hash=_require_str(
            payload["source_scan_result_hash"],
            field_name="source_scan_result_hash",
        ),
    )


def _decode_theme_record(value) -> ReplayThemeRecord:
    payload = _require_mapping(value, label="ReplayThemeRecord")
    _require_exact_fields(
        payload,
        _REPLAY_THEME_RECORD_FIELDS,
        label="ReplayThemeRecord",
    )
    market_batch = payload["market_batch"]
    scan_result = payload["scan_result"]
    allocation = payload["allocation"]
    return ReplayThemeRecord(
        theme_id=_require_str(payload["theme_id"], field_name="theme_id"),
        registered=_require_bool(
            payload["registered"],
            field_name="registered",
        ),
        market_batch=(
            None
            if market_batch is None
            else _decode_market_batch(market_batch)
        ),
        scan_result=(
            None
            if scan_result is None
            else _decode_scan_result(scan_result)
        ),
        allocation=(
            None
            if allocation is None
            else _decode_allocation(allocation)
        ),
        replay_status=ReplayStatus(
            _require_str(
                payload["replay_status"],
                field_name="replay_status",
            )
        ),
    )


def _decode_replay_result(value) -> ReplayCycleResult:
    payload = _require_mapping(value, label="ReplayCycleResult")
    _require_exact_fields(
        payload,
        _REPLAY_RESULT_FIELDS,
        label="ReplayCycleResult",
    )
    return ReplayCycleResult(
        cycle_as_of=_require_str(
            payload["cycle_as_of"],
            field_name="cycle_as_of",
        ),
        market_batches=tuple(
            _decode_market_batch(item)
            for item in _require_list(
                payload["market_batches"],
                field_name="market_batches",
            )
        ),
        combined_observations=tuple(
            _decode_theme_scan_observation(item)
            for item in _require_list(
                payload["combined_observations"],
                field_name="combined_observations",
            )
        ),
        scan_results=tuple(
            _decode_scan_result(item)
            for item in _require_list(
                payload["scan_results"],
                field_name="scan_results",
            )
        ),
        allocations=tuple(
            _decode_allocation(item)
            for item in _require_list(
                payload["allocations"],
                field_name="allocations",
            )
        ),
        theme_records=tuple(
            _decode_theme_record(item)
            for item in _require_list(
                payload["theme_records"],
                field_name="theme_records",
            )
        ),
        input_hash=_require_str(
            payload["input_hash"],
            field_name="input_hash",
        ),
        result_hash=_require_str(
            payload["result_hash"],
            field_name="result_hash",
        ),
    )


def _decode_archive_record(payload) -> ReplayArchiveRecord:
    data = _require_mapping(payload, label="archive")
    _require_exact_fields(
        data,
        _ARCHIVE_FIELDS,
        label="archive",
    )
    record = ReplayArchiveRecord(
        schema_version=_require_str(
            data["schema_version"],
            field_name="schema_version",
        ),
        content_type=_require_str(
            data["content_type"],
            field_name="content_type",
        ),
        producer=_require_str(
            data["producer"],
            field_name="producer",
        ),
        cycle_as_of=_require_str(
            data["cycle_as_of"],
            field_name="cycle_as_of",
        ),
        replay_input_hash=_require_str(
            data["replay_input_hash"],
            field_name="replay_input_hash",
        ),
        replay_result_hash=_require_str(
            data["replay_result_hash"],
            field_name="replay_result_hash",
        ),
        replay_result=_decode_replay_result(data["replay_result"]),
        archive_record_hash=_require_str(
            data["archive_record_hash"],
            field_name="archive_record_hash",
        ),
    )
    _validate_archive_record(record)
    return record


def _reject_json_constant(value: str):
    raise ValueError(f"non-finite JSON constant: {value}")


def read_replay_archive(path: str | Path) -> ReplayArchiveRecord:
    target = Path(path)
    payload = json.loads(
        target.read_text(encoding="utf-8"),
        parse_constant=_reject_json_constant,
    )
    record = _decode_archive_record(payload)

    expected_name = f"{record.replay_result_hash}.json"
    if target.name != expected_name:
        raise ValueError("archive filename mismatch")

    expected_cycle = _parse_cycle_date(record.cycle_as_of).isoformat()
    if target.parent.name != expected_cycle:
        raise ValueError("archive cycle directory mismatch")

    return record


def verify_replay_archive(path: str | Path) -> bool:
    try:
        read_replay_archive(path)
    except FileNotFoundError:
        return False
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
    return True



def _contains_path_sequence(
    parts: tuple[str, ...],
    sequence: tuple[str, ...],
) -> bool:
    width = len(sequence)
    return any(
        tuple(parts[index : index + width]) == sequence
        for index in range(len(parts) - width + 1)
    )


def _resolved_archive_root(archive_root: str | Path) -> Path:
    return Path(archive_root).expanduser().resolve(strict=False)


def _validate_destination_policy(
    archive_root: str | Path,
    *,
    destination_visibility: ArchiveDestinationVisibility,
    public_safe: bool,
) -> Path:
    if not isinstance(
        destination_visibility,
        ArchiveDestinationVisibility,
    ):
        raise TypeError("invalid archive destination visibility")

    resolved = _resolved_archive_root(archive_root)
    parts = tuple(resolved.parts)

    if _contains_path_sequence(parts, ("ledger", "live")):
        raise ValueError(
            "replay archives may not be written under ledger/live"
        )

    if destination_visibility is ArchiveDestinationVisibility.PUBLIC:
        if not public_safe:
            raise PermissionError(
                "public archive write requires explicit public_safe=True"
            )
        if len(parts) < 2 or parts[-2:] != (
            "recomputed",
            "replay_cycles",
        ):
            raise ValueError(
                "public replay archives must use recomputed/replay_cycles"
            )

    return resolved


def _serialize_archive_record(record: ReplayArchiveRecord) -> bytes:
    return (
        json.dumps(
            _record_payload(record),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def write_replay_archive(
    record: ReplayArchiveRecord,
    archive_root: str | Path,
    *,
    destination_visibility: ArchiveDestinationVisibility,
    public_safe: bool = False,
) -> ReplayArchiveWriteResult:
    resolved_root = _validate_destination_policy(
        archive_root,
        destination_visibility=destination_visibility,
        public_safe=public_safe,
    )
    _validate_archive_record(record)

    path = replay_archive_path(record, resolved_root)
    requested_payload = _record_payload(record)
    requested_bytes = _serialize_archive_record(record)

    path.parent.mkdir(parents=True, exist_ok=True)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        try:
            existing = read_replay_archive(path)
        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
            FileNotFoundError,
        ) as exc:
            raise FileExistsError("archive path conflict") from exc

        if _record_payload(existing) != requested_payload:
            raise FileExistsError("archive path conflict")

        return ReplayArchiveWriteResult(
            path=path,
            created=False,
            replay_result_hash=record.replay_result_hash,
            archive_record_hash=record.archive_record_hash,
        )

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(requested_bytes)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    return ReplayArchiveWriteResult(
        path=path,
        created=True,
        replay_result_hash=record.replay_result_hash,
        archive_record_hash=record.archive_record_hash,
    )
