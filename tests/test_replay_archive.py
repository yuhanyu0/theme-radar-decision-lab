from dataclasses import asdict, replace
import json
import os
from pathlib import Path

import pytest

from decision_lab.ledger import canonical_hash
from decision_lab.replay import ReplayCycleInput, ReplayStatus, run_replay_cycle
from decision_lab.replay_archive import (
    ArchiveDestinationVisibility,
    ReplayArchiveRecord,
    ReplayArchiveWriteResult,
    build_replay_archive_record,
    read_replay_archive,
    replay_archive_path,
    verify_replay_archive,
    write_replay_archive,
)
from decision_lab.research_budget import ResearchBudgetConfig, ResearchTier
from decision_lab.scanner import ScannerConfig, SupportDirection, ThemeScanObservation


def _radar(theme="Rates", *, discovery=0.8):
    return ThemeScanObservation(
        theme_id=theme,
        as_of="2026-09-19",
        source_type="radar_model_output",
        source_ref=f"radar:{theme}:2026-09-19",
        discovery_signal=discovery,
        novelty_signal=0.6,
        support_direction=SupportDirection.SUPPORTING,
        evidence_refs=(f"radar:{theme}",),
        is_independent=False,
        observed_or_inferred="inferred",
    )


def _sample_replay_result(*, cycle_as_of="2026-09-19"):
    return run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of=cycle_as_of,
            themes=(),
            external_observations=(_radar(),),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )


def test_build_record_is_deterministic_and_content_addressed():
    result = _sample_replay_result()

    first = build_replay_archive_record(result)
    second = build_replay_archive_record(result)

    assert first == second
    assert first.schema_version == "0.1"
    assert first.content_type == "replay_cycle_result"
    assert first.producer == "theme-radar-decision-lab/replay-archive@0.1"
    assert first.cycle_as_of == result.cycle_as_of
    assert first.replay_input_hash == result.input_hash
    assert first.replay_result_hash == result.result_hash
    assert first.replay_result == result
    assert len(first.archive_record_hash) == 64

    payload = {
        "schema_version": first.schema_version,
        "content_type": first.content_type,
        "producer": first.producer,
        "cycle_as_of": first.cycle_as_of,
        "replay_input_hash": first.replay_input_hash,
        "replay_result_hash": first.replay_result_hash,
        "replay_result": asdict(first.replay_result),
    }
    assert first.archive_record_hash == canonical_hash(payload)


def test_build_rejects_tampered_nested_replay_result_hash():
    result = _sample_replay_result()
    tampered = replace(result, result_hash="0" * 64)

    with pytest.raises(ValueError, match="replay result hash mismatch"):
        build_replay_archive_record(tampered)


@pytest.mark.parametrize(
    "bad_hash",
    [
        "abc",
        "A" * 64,
        "g" * 64,
        "0" * 63,
    ],
)
def test_build_rejects_malformed_replay_hashes(bad_hash):
    result = _sample_replay_result()
    invalid = replace(result, input_hash=bad_hash)

    with pytest.raises(ValueError, match="replay input hash"):
        build_replay_archive_record(invalid)


def test_archive_path_uses_utc_cycle_date():
    result = _sample_replay_result(
        cycle_as_of="2026-09-19T23:30:00-04:00"
    )
    record = build_replay_archive_record(result)

    path = replay_archive_path(
        record,
        Path("/tmp/archive-root"),
    )

    assert path == (
        Path("/tmp/archive-root")
        / "2026-09-20"
        / f"{record.replay_result_hash}.json"
    )


def test_archive_path_does_not_create_directories(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "not-created"

    path = replay_archive_path(record, root)

    assert path.parent == root / "2026-09-19"
    assert not root.exists()


def test_build_rejects_non_finite_replay_payload():
    result = _sample_replay_result()
    bad_scan = replace(result.scan_results[0], research_priority=float("nan"))
    bad = replace(result, scan_results=(bad_scan,))

    with pytest.raises(ValueError):
        build_replay_archive_record(bad)



def _record_payload(record):
    return {
        "schema_version": record.schema_version,
        "content_type": record.content_type,
        "producer": record.producer,
        "cycle_as_of": record.cycle_as_of,
        "replay_input_hash": record.replay_input_hash,
        "replay_result_hash": record.replay_result_hash,
        "replay_result": asdict(record.replay_result),
        "archive_record_hash": record.archive_record_hash,
    }


def _write_payload(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _standard_path(tmp_path, record):
    return (
        tmp_path
        / "2026-09-19"
        / f"{record.replay_result_hash}.json"
    )


def test_reader_round_trips_typed_replay_result(tmp_path):
    result = _sample_replay_result()
    record = build_replay_archive_record(result)
    path = _standard_path(tmp_path, record)
    _write_payload(path, _record_payload(record))

    loaded = read_replay_archive(path)

    assert loaded == record
    assert loaded.replay_result == result
    assert loaded.replay_result.theme_records[0].replay_status is ReplayStatus.ROUTED
    assert loaded.replay_result.allocations[0].tier is ResearchTier.SCAN_ONLY
    assert verify_replay_archive(path)


@pytest.mark.parametrize(
    "mutation",
    [
        "allocation_tier",
        "scan_priority",
        "embedded_result_hash",
        "top_result_hash",
        "top_input_hash",
        "archive_hash",
    ],
)
def test_tampering_invalidates_archive(tmp_path, mutation):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)

    if mutation == "allocation_tier":
        payload["replay_result"]["allocations"][0]["tier"] = (
            "FULL_DECISION_RESEARCH"
        )
    elif mutation == "scan_priority":
        payload["replay_result"]["scan_results"][0]["research_priority"] = 0.99
    elif mutation == "embedded_result_hash":
        payload["replay_result"]["result_hash"] = "1" * 64
    elif mutation == "top_result_hash":
        payload["replay_result_hash"] = "1" * 64
    elif mutation == "top_input_hash":
        payload["replay_input_hash"] = "1" * 64
    elif mutation == "archive_hash":
        payload["archive_record_hash"] = "1" * 64

    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError):
        read_replay_archive(path)


def test_reader_rejects_extra_top_level_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["unexpected"] = "value"
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(ValueError, match="unexpected archive fields"):
        read_replay_archive(path)


def test_reader_rejects_extra_nested_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["allocations"][0]["unexpected"] = 1
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(ValueError, match="unexpected ResearchAllocation fields"):
        read_replay_archive(path)


def test_reader_rejects_missing_nested_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["scan_results"][0].pop("theme_id")
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(ValueError, match="missing ThemeScanResult fields"):
        read_replay_archive(path)


def test_reader_rejects_invalid_nested_enum(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["theme_records"][0]["replay_status"] = "magic"
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(ValueError):
        read_replay_archive(path)


def test_reader_rejects_string_for_numeric_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["scan_results"][0]["research_priority"] = "0.5"
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(TypeError, match="research_priority"):
        read_replay_archive(path)


def test_reader_rejects_non_string_identity_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["scan_results"][0]["theme_id"] = 123
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(TypeError, match="theme_id"):
        read_replay_archive(path)


def test_reader_rejects_non_finite_json_constant(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["scan_results"][0]["research_priority"] = float("nan")
    path = _standard_path(tmp_path, record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, allow_nan=True),
        encoding="utf-8",
    )

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        read_replay_archive(path)


def test_reader_rejects_missing_top_level_field(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload.pop("producer")
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    with pytest.raises(ValueError, match="missing archive fields"):
        read_replay_archive(path)


def test_reader_rejects_wrong_filename(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    path = tmp_path / "2026-09-19" / f"{'1' * 64}.json"
    _write_payload(path, _record_payload(record))

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError, match="archive filename mismatch"):
        read_replay_archive(path)


def test_reader_rejects_wrong_cycle_directory(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    path = tmp_path / "2026-09-18" / f"{record.replay_result_hash}.json"
    _write_payload(path, _record_payload(record))

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError, match="archive cycle directory mismatch"):
        read_replay_archive(path)


def test_verify_returns_false_for_missing_and_malformed_json(tmp_path):
    missing = tmp_path / "missing.json"
    assert not verify_replay_archive(missing)

    malformed = tmp_path / "bad" / "payload.json"
    malformed.parent.mkdir(parents=True)
    malformed.write_text("{not-json", encoding="utf-8")
    assert not verify_replay_archive(malformed)



def test_public_write_requires_explicit_public_safe_before_directory_creation(
    tmp_path,
):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "recomputed" / "replay_cycles"

    with pytest.raises(
        PermissionError,
        match="public archive write requires explicit public_safe=True",
    ):
        write_replay_archive(
            record,
            root,
            destination_visibility=ArchiveDestinationVisibility.PUBLIC,
            public_safe=False,
        )

    assert not root.exists()


def test_public_write_requires_canonical_root_suffix(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "reports" / "replay_cycles"

    with pytest.raises(
        ValueError,
        match="public replay archives must use recomputed/replay_cycles",
    ):
        write_replay_archive(
            record,
            root,
            destination_visibility=ArchiveDestinationVisibility.PUBLIC,
            public_safe=True,
        )

    assert not root.exists()


@pytest.mark.parametrize(
    "visibility",
    [
        ArchiveDestinationVisibility.PUBLIC,
        ArchiveDestinationVisibility.PRIVATE,
    ],
)
def test_ledger_live_destination_is_always_rejected(tmp_path, visibility):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "ledger" / "live" / "replay_cycles"

    with pytest.raises(
        ValueError,
        match="replay archives may not be written under ledger/live",
    ):
        write_replay_archive(
            record,
            root,
            destination_visibility=visibility,
            public_safe=True,
        )

    assert not root.exists()


def test_private_destination_allows_public_safe_false(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "private-replays"

    result = write_replay_archive(
        record,
        root,
        destination_visibility=ArchiveDestinationVisibility.PRIVATE,
        public_safe=False,
    )

    assert result.created
    assert result.path.exists()


def test_same_record_write_is_idempotent(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "recomputed" / "replay_cycles"

    first = write_replay_archive(
        record,
        root,
        destination_visibility=ArchiveDestinationVisibility.PUBLIC,
        public_safe=True,
    )
    second = write_replay_archive(
        record,
        root,
        destination_visibility=ArchiveDestinationVisibility.PUBLIC,
        public_safe=True,
    )

    assert first.created
    assert not second.created
    assert first.path == second.path
    assert first.archive_record_hash == second.archive_record_hash
    assert first.replay_result_hash == second.replay_result_hash
    assert list(first.path.parent.glob("*.json")) == [first.path]


def test_existing_conflicting_file_is_never_overwritten(tmp_path):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "private"
    path = replay_archive_path(record, root)
    path.parent.mkdir(parents=True)
    original = b"{\"different\":true}\n"
    path.write_bytes(original)

    with pytest.raises(FileExistsError, match="archive path conflict"):
        write_replay_archive(
            record,
            root,
            destination_visibility=ArchiveDestinationVisibility.PRIVATE,
        )

    assert path.read_bytes() == original


def test_symlink_resolving_under_ledger_live_is_rejected(tmp_path):
    target = tmp_path / "ledger" / "live" / "real"
    target.mkdir(parents=True)
    link = tmp_path / "archive-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unsupported")

    record = build_replay_archive_record(_sample_replay_result())
    with pytest.raises(
        ValueError,
        match="replay archives may not be written under ledger/live",
    ):
        write_replay_archive(
            record,
            link,
            destination_visibility=ArchiveDestinationVisibility.PRIVATE,
        )


def test_public_symlink_to_noncanonical_destination_is_rejected(tmp_path):
    target = tmp_path / "reports" / "replay_cycles"
    target.mkdir(parents=True)
    link_parent = tmp_path / "recomputed"
    link_parent.mkdir()
    link = link_parent / "replay_cycles"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unsupported")

    record = build_replay_archive_record(_sample_replay_result())
    with pytest.raises(
        ValueError,
        match="public replay archives must use recomputed/replay_cycles",
    ):
        write_replay_archive(
            record,
            link,
            destination_visibility=ArchiveDestinationVisibility.PUBLIC,
            public_safe=True,
        )
