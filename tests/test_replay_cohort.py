from dataclasses import asdict, replace

import pytest

from decision_lab.ledger import canonical_hash
from decision_lab.replay import ReplayCycleInput, ReplayStatus, run_replay_cycle
from decision_lab.replay_archive import build_replay_archive_record
from decision_lab.replay_cohort import (
    ContradictionTransition,
    EvidenceClass,
    FuturePresence,
    IndependentEvidenceState,
    ReplayCohortResult,
    ReplayCohortSummary,
    ReplayCohortTransition,
    RoutingIntent,
    TierTransition,
    evaluate_replay_cohort,
)
from decision_lab.research_budget import ResearchBudgetConfig, ResearchTier
from decision_lab.scanner import (
    ScannerConfig,
    SupportDirection,
    ThemeScanObservation,
)


def _radar(theme="Rates", *, as_of="2026-09-19"):
    return ThemeScanObservation(
        theme_id=theme,
        as_of=as_of,
        source_type="radar_model_output",
        source_ref=f"radar:{theme}:{as_of}",
        discovery_signal=0.8,
        novelty_signal=0.6,
        support_direction=SupportDirection.SUPPORTING,
        evidence_refs=(f"radar:{theme}",),
        is_independent=False,
        observed_or_inferred="inferred",
    )


def _archive(
    *,
    cycle_as_of="2026-09-19",
    observations=None,
):
    observations = (
        (_radar(as_of=cycle_as_of),)
        if observations is None
        else tuple(observations)
    )
    result = run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of=cycle_as_of,
            themes=(),
            external_observations=observations,
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
    return build_replay_archive_record(result)


def test_empty_cohort_is_valid_and_deterministic():
    first = evaluate_replay_cohort((), horizons=(5, 1, 3))
    second = evaluate_replay_cohort((), horizons=(1, 3, 5))

    assert first == second
    assert first.schema_version == "0.1"
    assert (
        first.evaluation_scope
        == "evidence_evolution_and_descriptive_system_transition"
    )
    assert first.horizons == (1, 3, 5)
    assert first.cycles == ()
    assert first.archive_record_hashes == ()
    assert first.transitions == ()
    assert first.summaries == ()
    assert len(first.input_hash) == 64
    assert len(first.result_hash) == 64
    assert "directional price prediction" in first.limitations[-1]


@pytest.mark.parametrize("bad", [0, -1, 1.0, "1", True, False])
def test_invalid_horizon_is_rejected(bad):
    with pytest.raises(
        ValueError,
        match="cohort horizons must be positive integers",
    ):
        evaluate_replay_cohort((), horizons=(bad,))


def test_duplicate_horizon_is_rejected():
    with pytest.raises(ValueError, match="duplicate cohort horizon"):
        evaluate_replay_cohort((), horizons=(1, 3, 1))


def test_record_input_order_is_irrelevant():
    first_record = _archive(cycle_as_of="2026-09-19")
    second_record = _archive(cycle_as_of="2026-09-20")

    first = evaluate_replay_cohort(
        (first_record, second_record),
        horizons=(1,),
    )
    second = evaluate_replay_cohort(
        (second_record, first_record),
        horizons=(1,),
    )

    assert first == second
    assert first.cycles == ("2026-09-19", "2026-09-20")


def test_duplicate_archive_record_is_rejected():
    record = _archive()

    with pytest.raises(
        ValueError,
        match="duplicate replay archive record",
    ):
        evaluate_replay_cohort((record, record), horizons=(1,))


def test_distinct_archives_at_same_normalized_cycle_are_ambiguous():
    date_record = _archive(
        cycle_as_of="2026-09-19",
        observations=(_radar("Rates", as_of="2026-09-19"),),
    )
    timestamp_record = _archive(
        cycle_as_of="2026-09-19T23:59:59.999999+00:00",
        observations=(
            _radar(
                "OtherTheme",
                as_of="2026-09-19T23:59:59.999999+00:00",
            ),
        ),
    )

    with pytest.raises(ValueError, match="ambiguous cohort cycle"):
        evaluate_replay_cohort(
            (date_record, timestamp_record),
            horizons=(1,),
        )


def _rehash_result(result):
    payload = {
        "cycle_as_of": result.cycle_as_of,
        "input_hash": result.input_hash,
        "market_batches": [asdict(x) for x in result.market_batches],
        "combined_observations": [
            asdict(x) for x in result.combined_observations
        ],
        "scan_results": [asdict(x) for x in result.scan_results],
        "allocations": [asdict(x) for x in result.allocations],
        "theme_records": [asdict(x) for x in result.theme_records],
    }
    return replace(result, result_hash=canonical_hash(payload))


def _archive_from_semantically_modified_result(result):
    return build_replay_archive_record(_rehash_result(result))


def test_hash_valid_duplicate_theme_records_are_rejected():
    record = _archive()
    result = record.replay_result
    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            theme_records=(
                result.theme_records[0],
                result.theme_records[0],
            ),
        )
    )

    with pytest.raises(ValueError, match="inconsistent replay theme record"):
        evaluate_replay_cohort((bad,), horizons=(1,))


def test_hash_valid_routed_record_must_match_top_level_scan():
    record = _archive()
    result = record.replay_result
    theme_record = result.theme_records[0]
    changed_scan = replace(
        theme_record.scan_result,
        research_priority=0.123,
    )
    bad_record = replace(
        theme_record,
        scan_result=changed_scan,
    )
    bad = _archive_from_semantically_modified_result(
        replace(result, theme_records=(bad_record,))
    )

    with pytest.raises(ValueError, match="inconsistent replay theme record"):
        evaluate_replay_cohort((bad,), horizons=(1,))


def test_hash_valid_allocation_scan_hash_mismatch_is_rejected():
    record = _archive()
    result = record.replay_result
    allocation = replace(
        result.allocations[0],
        source_scan_result_hash="0" * 64,
    )
    theme_record = replace(
        result.theme_records[0],
        allocation=allocation,
    )
    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            allocations=(allocation,),
            theme_records=(theme_record,),
        )
    )

    with pytest.raises(
        ValueError,
        match="allocation scan-result hash mismatch",
    ):
        evaluate_replay_cohort((bad,), horizons=(1,))


def test_hash_valid_observation_without_theme_record_is_rejected():
    record = _archive()
    result = record.replay_result
    extra = _radar("Ghost", as_of=result.cycle_as_of)
    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            combined_observations=(
                *result.combined_observations,
                extra,
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match="observation theme missing from replay records",
    ):
        evaluate_replay_cohort((bad,), horizons=(1,))
