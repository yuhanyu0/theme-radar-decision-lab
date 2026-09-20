import json
import os
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from decision_lab.ledger import canonical_hash
from decision_lab.market_observation import (
    MarketBar,
    MarketObservationConfig,
    MarketObservationMode,
    MarketObservationSpec,
    load_market_observation_config,
    load_market_observation_spec,
)
from decision_lab.replay import (
    ReplayCycleInput,
    ReplayStatus,
    ThemeReplayInput,
    run_replay_cycle,
)
from decision_lab.replay_archive import (
    ArchiveDestinationVisibility,
    build_replay_archive_record,
    read_replay_archive,
    replay_archive_path,
    verify_replay_archive,
    write_replay_archive,
)
from decision_lab.research_budget import ResearchBudgetConfig, ResearchTier
from decision_lab.scanner import ScannerConfig, SupportDirection, ThemeScanObservation
from decision_lab.themes import (
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemeLifecycleState,
    ThemePackage,
    load_theme_package,
)
from decision_lab.universe import Candidate, ThemeLayer, ThemeUniverse


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



def test_partial_new_file_is_removed_after_write_failure(tmp_path, monkeypatch):
    record = build_replay_archive_record(_sample_replay_result())
    root = tmp_path / "private"

    class BrokenWriter:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def write(self, data):
            raise OSError("simulated write failure")

    real_fdopen = os.fdopen

    def broken_fdopen(fd, mode):
        os.close(fd)
        return BrokenWriter()

    monkeypatch.setattr(os, "fdopen", broken_fdopen)

    with pytest.raises(OSError, match="simulated write failure"):
        write_replay_archive(
            record,
            root,
            destination_visibility=ArchiveDestinationVisibility.PRIVATE,
        )

    path = replay_archive_path(record, root.resolve(strict=False))
    assert not path.exists()

    monkeypatch.setattr(os, "fdopen", real_fdopen)


def _market_replay_result():
    universe = ThemeUniverse(
        theme="ArchiveTheme",
        version="u1",
        generated_at="2026-09-19T00:00:00Z",
    )
    universe.add_layer(ThemeLayer("layer"))
    universe.add_candidate(
        Candidate(
            ticker="AAA",
            theme="ArchiveTheme",
            layer="layer",
            effective_from="2026-01-01",
        )
    )
    package = ThemePackage(
        definition=ThemeDefinition(
            theme_id="ArchiveTheme",
            display_name="Archive Theme",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            effective_from="2026-01-01",
            version="1",
        ),
        universe=universe,
        theme_key_policy=ThemeKeyPolicy(),
        evidence_adapter="generic",
        version="p1",
        source_path="fixture",
    )
    spec = MarketObservationSpec(
        theme_id="ArchiveTheme",
        mode=MarketObservationMode.BASKET,
        benchmark="SPY",
        current_return_sessions=1,
        prior_return_sessions=1,
        min_basket_members=1,
        version="test",
    )
    bars = tuple(
        MarketBar(
            symbol=symbol,
            session_date=session,
            available_at=f"{session}T21:00:00+00:00",
            close=close,
        )
        for symbol, closes in (
            ("SPY", (100, 100, 100)),
            ("AAA", (100, 100, 103)),
        )
        for session, close in zip(
            ("2026-09-17", "2026-09-18", "2026-09-19"),
            closes,
            strict=True,
        )
    )
    return run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of="2026-09-19",
            themes=(
                ThemeReplayInput(
                    package=package,
                    market_spec=spec,
                    market_config=MarketObservationConfig(),
                    bars=bars,
                    market_source_ref="fixture:archive-market",
                ),
            ),
            external_observations=(),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )


def test_nested_market_diagnostic_tamper_is_detected(tmp_path):
    record = build_replay_archive_record(_market_replay_result())
    payload = _record_payload(record)
    payload["replay_result"]["market_batches"][0]["diagnostics"][0][
        "current_excess_return"
    ] = 0.99
    path = (
        tmp_path
        / "2026-09-19"
        / f"{record.replay_result_hash}.json"
    )
    _write_payload(path, payload)

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError):
        read_replay_archive(path)


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("schema_version", "9.9"),
        ("content_type", "other"),
        ("producer", "other-producer"),
    ],
)
def test_reader_rejects_unsupported_archive_contract(
    tmp_path,
    field_name,
    bad_value,
):
    record = build_replay_archive_record(_sample_replay_result())
    payload = _record_payload(record)
    payload[field_name] = bad_value
    path = _standard_path(tmp_path, record)
    _write_payload(path, payload)

    assert not verify_replay_archive(path)
    with pytest.raises(ValueError):
        read_replay_archive(path)


def test_reader_rejects_non_object_top_level_json(tmp_path):
    path = tmp_path / "2026-09-19" / f"{'0' * 64}.json"
    _write_payload(path, ["not", "an", "object"])

    assert not verify_replay_archive(path)
    with pytest.raises(TypeError, match="archive must be a JSON object"):
        read_replay_archive(path)


ROOT = Path(__file__).resolve().parents[1]

REPLAY_SESSIONS = (
    "2026-09-03",
    "2026-09-04",
    "2026-09-08",
    "2026-09-09",
    "2026-09-10",
    "2026-09-11",
    "2026-09-14",
    "2026-09-15",
    "2026-09-16",
    "2026-09-17",
    "2026-09-18",
)


def _series(symbol, closes):
    return tuple(
        MarketBar(
            symbol=symbol,
            session_date=session,
            available_at=f"{session}T21:00:00+00:00",
            close=close,
        )
        for session, close in zip(REPLAY_SESSIONS, closes, strict=True)
    )


def _full_replay_result():
    market_config = load_market_observation_config(
        ROOT / "config/adapters/market_observation_defaults.yaml"
    )
    dc_package = load_theme_package(
        ROOT / "config/themes/datacenter_infra.yaml"
    )
    bio_package = load_theme_package(
        ROOT / "config/themes/genomics_bio.yaml"
    )
    dc_spec = load_market_observation_spec(
        ROOT / "config/market_observations/datacenter_infra.yaml"
    )
    bio_spec = load_market_observation_spec(
        ROOT / "config/market_observations/genomics_bio.yaml"
    )

    dc_bars = (
        _series("SPY", [100] * 11)
        + _series(
            "BE",
            [100, 102, 104, 106, 108, 110, 106, 102, 98, 94, 90],
        )
        + _series(
            "NRG",
            [100, 101, 102, 103, 104, 105, 102, 99, 96, 93, 90],
        )
        + _series(
            "CEG",
            [100, 102, 103, 105, 106, 108, 106, 103, 100, 98, 95],
        )
    )
    bio_bars = (
        _series("SPY", [100] * 11)
        + _series(
            "ARKG",
            [100, 99, 98, 97, 96, 95, 100, 105, 110, 115, 120],
        )
        + _series(
            "XBI",
            [100, 99, 98, 97, 96, 96, 96.2, 96.4, 96.6, 96.8, 97.0],
        )
    )

    quiet_universe = ThemeUniverse(
        theme="QuietTheme",
        version="u1",
        generated_at="2026-09-19T00:00:00Z",
    )
    quiet_universe.add_layer(ThemeLayer("layer"))
    quiet_package = ThemePackage(
        definition=ThemeDefinition(
            theme_id="QuietTheme",
            display_name="Quiet Theme",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            effective_from="2026-01-01",
            version="1",
        ),
        universe=quiet_universe,
        theme_key_policy=ThemeKeyPolicy(),
        evidence_adapter="generic",
        version="p1",
        source_path="fixture",
    )
    quiet_spec = MarketObservationSpec(
        theme_id="QuietTheme",
        mode=MarketObservationMode.BASKET,
        benchmark="SPY",
        current_return_sessions=1,
        prior_return_sessions=1,
        min_basket_members=1,
        version="test",
    )

    def radar(theme, discovery, novelty):
        return ThemeScanObservation(
            theme_id=theme,
            as_of="2026-09-19",
            source_type="radar_model_output",
            source_ref=f"radar:{theme}:2026-09-19",
            discovery_signal=discovery,
            novelty_signal=novelty,
            support_direction=SupportDirection.SUPPORTING,
            evidence_refs=(f"radar:{theme}",),
            is_independent=False,
            observed_or_inferred="inferred",
        )

    return run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of="2026-09-19",
            themes=(
                ThemeReplayInput(
                    package=dc_package,
                    market_spec=dc_spec,
                    market_config=market_config,
                    bars=dc_bars,
                    market_source_ref="fixture:archive:datacenter",
                ),
                ThemeReplayInput(
                    package=bio_package,
                    market_spec=bio_spec,
                    market_config=market_config,
                    bars=bio_bars,
                    market_source_ref="fixture:archive:genomics",
                ),
                ThemeReplayInput(
                    package=quiet_package,
                    market_spec=quiet_spec,
                    market_config=market_config,
                    bars=(
                        MarketBar(
                            symbol="SPY",
                            session_date="2026-09-19",
                            available_at="2026-09-19T21:00:00+00:00",
                            close=100,
                        ),
                    ),
                    market_source_ref="fixture:archive:quiet",
                ),
            ),
            external_observations=(
                radar("DataCenter_Infra", 0.9, 0.8),
                radar("Genomics_Bio", 0.85, 0.75),
                radar("Rates", 0.8, 0.6),
            ),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )


def test_write_read_verify_round_trip_preserves_full_typed_result(tmp_path):
    replay_result = _full_replay_result()
    record = build_replay_archive_record(replay_result)
    root = tmp_path / "recomputed" / "replay_cycles"

    written = write_replay_archive(
        record,
        root,
        destination_visibility=ArchiveDestinationVisibility.PUBLIC,
        public_safe=True,
    )
    loaded = read_replay_archive(written.path)

    assert verify_replay_archive(written.path)
    assert loaded == record
    assert loaded.replay_result == replay_result


def test_archive_identity_is_independent_of_root_and_mtime(tmp_path):
    replay_result = _full_replay_result()
    first_record = build_replay_archive_record(replay_result)
    second_record = build_replay_archive_record(replay_result)
    assert first_record == second_record

    first = write_replay_archive(
        first_record,
        tmp_path / "private-a",
        destination_visibility=ArchiveDestinationVisibility.PRIVATE,
    )
    second = write_replay_archive(
        second_record,
        tmp_path / "private-b",
        destination_visibility=ArchiveDestinationVisibility.PRIVATE,
    )

    os.utime(first.path, (1_000_000, 1_000_000))

    assert verify_replay_archive(first.path)
    assert verify_replay_archive(second.path)
    assert read_replay_archive(first.path) == read_replay_archive(second.path)


def test_replay_archive_interfaces_are_publicly_importable():
    import decision_lab

    for name in (
        "ArchiveDestinationVisibility",
        "ReplayArchiveRecord",
        "ReplayArchiveWriteResult",
        "build_replay_archive_record",
        "read_replay_archive",
        "replay_archive_path",
        "verify_replay_archive",
        "write_replay_archive",
    ):
        assert getattr(decision_lab, name) is not None
