from dataclasses import asdict, replace
from pathlib import Path

import pytest

from decision_lab.ledger import canonical_hash
from decision_lab.replay import ReplayCycleInput, run_replay_cycle
from decision_lab.replay_archive import (
    ArchiveDestinationVisibility,
    ReplayArchiveRecord,
    ReplayArchiveWriteResult,
    build_replay_archive_record,
    replay_archive_path,
)
from decision_lab.research_budget import ResearchBudgetConfig
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
