from dataclasses import asdict, replace

import pytest

from decision_lab.ledger import canonical_hash
from decision_lab.market_observation import (
    MarketBar,
    MarketObservationConfig,
    MarketObservationMode,
    MarketObservationSpec,
)
from decision_lab.replay import (
    ReplayCycleInput,
    ReplayStatus,
    ThemeReplayInput,
    run_replay_cycle,
)
from decision_lab.replay_archive import build_replay_archive_record
from decision_lab.replay_cohort import (
    ContradictionTransition,
    EvidenceClass,
    FuturePresence,
    RoutingIntent,
    TierTransition,
    _independent_evidence_state,
    _routing_intent,
    evaluate_replay_cohort,
)
from decision_lab.research_budget import ResearchBudgetConfig, ResearchTier
from decision_lab.scanner import (
    ScannerConfig,
    SupportDirection,
    ThemeScanObservation,
)
from decision_lab.themes import (
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemeLifecycleState,
    ThemePackage,
)
from decision_lab.universe import Candidate, ThemeLayer, ThemeUniverse


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



def _independent(
    theme,
    source_ref,
    direction,
    *,
    as_of="2026-09-19",
):
    return ThemeScanObservation(
        theme_id=theme,
        as_of=as_of,
        source_type="derived_feature",
        source_ref=source_ref,
        discovery_signal=0.9,
        structure_signal=0.9,
        persistence_signal=0.9,
        breadth_signal=0.9,
        relative_strength_signal=0.9,
        novelty_signal=0.9,
        support_direction=direction,
        evidence_refs=(source_ref,),
        is_independent=True,
        observed_or_inferred="inferred",
    )


@pytest.mark.parametrize(
    ("observations", "expected_class", "counts"),
    [
        ((), EvidenceClass.NO_INDEPENDENT, (0, 0, 0, 0)),
        (
            (_independent("T", "s1", SupportDirection.SUPPORTING),),
            EvidenceClass.SUPPORT_ONLY,
            (1, 1, 0, 0),
        ),
        (
            (_independent("T", "s1", SupportDirection.CONTRADICTING),),
            EvidenceClass.CONTRADICTION_PRESENT,
            (1, 0, 1, 0),
        ),
        (
            (_independent("T", "s1", SupportDirection.NEUTRAL),),
            EvidenceClass.NEUTRAL_ONLY,
            (1, 0, 0, 1),
        ),
        (
            (
                _independent("T", "a", SupportDirection.SUPPORTING),
                _independent("T", "b", SupportDirection.CONTRADICTING),
            ),
            EvidenceClass.MIXED,
            (2, 1, 1, 0),
        ),
    ],
)
def test_independent_evidence_classification(
    observations,
    expected_class,
    counts,
):
    record = _archive(
        observations=(
            *observations,
            _radar("T"),
        )
    )
    state = _independent_evidence_state(
        record.replay_result,
        "T",
    )

    assert state.evidence_class is expected_class
    assert (
        state.independent_source_count,
        state.supporting_source_count,
        state.contradicting_source_count,
        state.neutral_source_count,
    ) == counts


def test_same_independent_source_counts_once_with_contradiction_precedence():
    observations = (
        _independent("T", "same", SupportDirection.SUPPORTING),
        _independent("T", "same", SupportDirection.CONTRADICTING),
    )
    record = _archive(observations=observations)

    state = _independent_evidence_state(
        record.replay_result,
        "T",
    )

    assert state.independent_source_count == 1
    assert state.supporting_source_count == 0
    assert state.contradicting_source_count == 1
    assert state.contradicting_source_refs == ("same",)


def test_conflicting_source_metadata_is_rejected_even_with_no_horizons():
    first = _independent("T", "same", SupportDirection.SUPPORTING)
    record = _archive(observations=(first,))
    result = record.replay_result
    conflicting = replace(
        first,
        source_type="industry_primary",
    )
    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            combined_observations=(
                *result.combined_observations,
                conflicting,
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match="conflicting cohort source metadata",
    ):
        evaluate_replay_cohort((bad,), horizons=())


def _package(theme):
    universe = ThemeUniverse(
        theme=theme,
        version="u1",
        generated_at="2026-09-19T00:00:00Z",
    )
    universe.add_layer(ThemeLayer("layer"))
    universe.add_candidate(
        Candidate(
            ticker=f"{theme[:3].upper()}1",
            theme=theme,
            layer="layer",
            effective_from="2026-01-01",
        )
    )
    return ThemePackage(
        definition=ThemeDefinition(
            theme_id=theme,
            display_name=theme,
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


def _theme_input(theme, cycle_as_of):
    return ThemeReplayInput(
        package=_package(theme),
        market_spec=MarketObservationSpec(
            theme_id=theme,
            mode=MarketObservationMode.BASKET,
            benchmark="SPY",
            current_return_sessions=1,
            prior_return_sessions=1,
            min_basket_members=1,
            version="test",
        ),
        market_config=MarketObservationConfig(),
        bars=(
            MarketBar(
                symbol="SPY",
                session_date=cycle_as_of[:10],
                available_at=f"{cycle_as_of[:10]}T21:00:00+00:00",
                close=100,
            ),
        ),
        market_source_ref=f"fixture:{theme}:{cycle_as_of}",
    )


def _registered_archive(
    *,
    cycle_as_of="2026-09-19",
    themes=("FullTheme",),
    observations=(),
    budget_config=None,
):
    result = run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of=cycle_as_of,
            themes=tuple(
                _theme_input(theme, cycle_as_of)
                for theme in themes
            ),
            external_observations=tuple(observations),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=(
                budget_config or ResearchBudgetConfig()
            ),
        )
    )
    return build_replay_archive_record(result)


def test_routing_intent_distinguishes_no_observation_and_ordinary_full():
    quiet = _registered_archive(
        themes=("Quiet",),
        observations=(),
    )
    assert (
        _routing_intent(quiet.replay_result.theme_records[0])
        is RoutingIntent.NO_OBSERVATION
    )

    full = _registered_archive(
        themes=("FullTheme",),
        observations=(
            _independent(
                "FullTheme",
                "independent:full",
                SupportDirection.SUPPORTING,
            ),
        ),
    )
    assert (
        _routing_intent(full.replay_result.theme_records[0])
        is RoutingIntent.ORDINARY_FULL_RESEARCH
    )


def test_routing_intent_distinguishes_forced_full_and_capacity_missed():
    contradiction = _independent(
        "RiskTheme",
        "independent:risk",
        SupportDirection.CONTRADICTING,
    )
    forced_full = _registered_archive(
        themes=("RiskTheme",),
        observations=(contradiction,),
    )
    assert (
        _routing_intent(forced_full.replay_result.theme_records[0])
        is RoutingIntent.FORCED_FULL_REVIEW
    )

    missed = _registered_archive(
        themes=("RiskTheme",),
        observations=(contradiction,),
        budget_config=replace(
            ResearchBudgetConfig(),
            full_decision_slots=0,
        ),
    )
    assert (
        _routing_intent(missed.replay_result.theme_records[0])
        is RoutingIntent.FORCED_REVIEW_CAPACITY_MISSED
    )


def test_routing_intent_classifies_unregistered_forced_review():
    record = _archive(
        observations=(
            _independent(
                "UnknownRisk",
                "unknown:risk",
                SupportDirection.CONTRADICTING,
            ),
        )
    )
    item = record.replay_result.theme_records[0]

    assert item.registered is False
    assert item.scan_result.forced_review
    assert item.allocation.tier is ResearchTier.SCAN_ONLY
    assert "theme not registered" in item.allocation.allocation_reasons
    assert (
        _routing_intent(item)
        is RoutingIntent.FORCED_REVIEW_UNREGISTERED
    )


def test_routing_intent_distinguishes_theme_research_and_scan_only():
    low_novelty = replace(
        _independent(
            "ResearchTheme",
            "independent:research",
            SupportDirection.SUPPORTING,
        ),
        novelty_signal=0.1,
    )
    theme_research = _registered_archive(
        themes=("ResearchTheme",),
        observations=(low_novelty,),
    )
    assert (
        _routing_intent(
            theme_research.replay_result.theme_records[0]
        )
        is RoutingIntent.ORDINARY_THEME_RESEARCH
    )

    scan_only = _archive(
        observations=(_radar("Rates"),),
    )
    assert (
        _routing_intent(scan_only.replay_result.theme_records[0])
        is RoutingIntent.SCAN_ONLY
    )


def test_forced_review_mismatch_is_rejected_even_with_no_horizons():
    record = _registered_archive(
        themes=("RiskTheme",),
        observations=(
            _independent(
                "RiskTheme",
                "risk",
                SupportDirection.CONTRADICTING,
            ),
        ),
    )
    result = record.replay_result
    allocation = replace(result.allocations[0], forced_review=False)
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

    with pytest.raises(ValueError, match="forced-review flag mismatch"):
        evaluate_replay_cohort((bad,), horizons=())



def test_one_cycle_emits_right_censored_rows_for_every_horizon():
    source = _archive()
    result = evaluate_replay_cohort(
        (source,),
        horizons=(1, 3),
    )

    assert len(result.transitions) == 2
    assert {
        item.horizon_cycles for item in result.transitions
    } == {1, 3}
    for item in result.transitions:
        assert item.future_presence is FuturePresence.RIGHT_CENSORED
        assert item.future_cycle_index is None
        assert item.future_cycle_as_of is None
        assert item.future_evidence_state is None
        assert item.future_tier is None
        assert item.priority_delta is None
        assert (
            item.contradiction_transition
            is ContradictionTransition.UNASSESSED
        )
        assert item.tier_transition is TierTransition.UNASSESSED


def test_future_not_present_is_not_scan_only_or_no_observation():
    source = _archive(cycle_as_of="2026-09-19")
    future = _archive(
        cycle_as_of="2026-09-20",
        observations=(_radar("Other", as_of="2026-09-20"),),
    )

    result = evaluate_replay_cohort(
        (source, future),
        horizons=(1,),
    )
    row = next(
        item
        for item in result.transitions
        if item.source_cycle_index == 0
        and item.theme_id == "Rates"
    )

    assert row.future_presence is FuturePresence.NOT_PRESENT
    assert row.future_registered is None
    assert row.future_replay_status is None
    assert row.future_evidence_state is None
    assert row.future_tier is None
    assert row.future_priority is None
    assert row.priority_delta is None
    assert row.tier_transition is TierTransition.UNASSESSED
    assert (
        row.contradiction_transition
        is ContradictionTransition.UNASSESSED
    )
    assert not any(
        item.source_cycle_index == 0 and item.theme_id == "Other"
        for item in result.transitions
    )


def test_future_present_no_observation_stays_distinct():
    source = _registered_archive(
        cycle_as_of="2026-09-19",
        themes=("Quiet",),
        observations=(),
    )
    future = _registered_archive(
        cycle_as_of="2026-09-20",
        themes=("Quiet",),
        observations=(),
    )

    result = evaluate_replay_cohort(
        (source, future),
        horizons=(1,),
    )
    row = result.transitions[0]

    assert row.future_presence is FuturePresence.PRESENT
    assert row.future_replay_status is ReplayStatus.NO_OBSERVATION
    assert row.future_tier is None
    assert (
        row.future_evidence_state.evidence_class
        is EvidenceClass.NO_INDEPENDENT
    )


def test_contradiction_requires_independent_evidence_on_both_sides():
    source = _archive(cycle_as_of="2026-09-19")
    future = _archive(
        cycle_as_of="2026-09-20",
        observations=(
            _independent(
                "Rates",
                "independent:risk",
                SupportDirection.CONTRADICTING,
                as_of="2026-09-20",
            ),
        ),
    )

    row = evaluate_replay_cohort(
        (source, future),
        horizons=(1,),
    ).transitions[0]

    assert (
        row.source_evidence_state.evidence_class
        is EvidenceClass.NO_INDEPENDENT
    )
    assert (
        row.contradiction_transition
        is ContradictionTransition.UNASSESSED
    )
    assert row.evidence_class_changed is None


@pytest.mark.parametrize(
    ("source_direction", "future_direction", "expected"),
    [
        (
            SupportDirection.SUPPORTING,
            SupportDirection.CONTRADICTING,
            ContradictionTransition.EMERGED,
        ),
        (
            SupportDirection.CONTRADICTING,
            SupportDirection.CONTRADICTING,
            ContradictionTransition.PERSISTED,
        ),
        (
            SupportDirection.CONTRADICTING,
            SupportDirection.SUPPORTING,
            ContradictionTransition.RESOLVED,
        ),
        (
            SupportDirection.SUPPORTING,
            SupportDirection.SUPPORTING,
            ContradictionTransition.ABSENT,
        ),
    ],
)
def test_contradiction_transition_with_comparable_independent_evidence(
    source_direction,
    future_direction,
    expected,
):
    source = _archive(
        cycle_as_of="2026-09-19",
        observations=(
            _independent(
                "T",
                "source",
                source_direction,
                as_of="2026-09-19",
            ),
        ),
    )
    future = _archive(
        cycle_as_of="2026-09-20",
        observations=(
            _independent(
                "T",
                "future",
                future_direction,
                as_of="2026-09-20",
            ),
        ),
    )

    row = evaluate_replay_cohort(
        (source, future),
        horizons=(1,),
    ).transitions[0]

    assert row.contradiction_transition is expected
    assert row.evidence_class_changed is (
        source_direction is not future_direction
    )


@pytest.mark.parametrize(
    ("source", "future", "expected"),
    [
        (
            ResearchTier.SCAN_ONLY,
            ResearchTier.SCAN_ONLY,
            TierTransition.SAME,
        ),
        (
            ResearchTier.SCAN_ONLY,
            ResearchTier.THEME_RESEARCH,
            TierTransition.ESCALATED,
        ),
        (
            ResearchTier.THEME_RESEARCH,
            ResearchTier.FULL_DECISION_RESEARCH,
            TierTransition.ESCALATED,
        ),
        (
            ResearchTier.FULL_DECISION_RESEARCH,
            ResearchTier.SCAN_ONLY,
            TierTransition.DEESCALATED,
        ),
        (
            None,
            ResearchTier.SCAN_ONLY,
            TierTransition.UNASSESSED,
        ),
        (
            ResearchTier.SCAN_ONLY,
            None,
            TierTransition.UNASSESSED,
        ),
    ],
)
def test_tier_transition_ordering(source, future, expected):
    from decision_lab.replay_cohort import _tier_transition

    assert _tier_transition(source, future) is expected



def _cycle_archive(
    cycle_as_of,
    *,
    dc_direction,
    bio_direction,
    include_rates,
):
    themes = (
        _theme_input("DataCenter_Infra", cycle_as_of),
        _theme_input("Genomics_Bio", cycle_as_of),
        _theme_input("Quiet", cycle_as_of),
    )
    observations = [
        _independent(
            "DataCenter_Infra",
            f"dc:{cycle_as_of}",
            dc_direction,
            as_of=cycle_as_of,
        ),
        _independent(
            "Genomics_Bio",
            f"bio:{cycle_as_of}",
            bio_direction,
            as_of=cycle_as_of,
        ),
    ]
    if include_rates:
        observations.append(
            _radar("Rates", as_of=cycle_as_of)
        )

    result = run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of=cycle_as_of,
            themes=themes,
            external_observations=tuple(observations),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
    return build_replay_archive_record(result)


def _three_cycle_cohort():
    c0 = _cycle_archive(
        "2026-09-19",
        dc_direction=SupportDirection.CONTRADICTING,
        bio_direction=SupportDirection.SUPPORTING,
        include_rates=True,
    )
    c1 = _cycle_archive(
        "2026-09-20",
        dc_direction=SupportDirection.CONTRADICTING,
        bio_direction=SupportDirection.SUPPORTING,
        include_rates=False,
    )
    c2 = _cycle_archive(
        "2026-09-21",
        dc_direction=SupportDirection.SUPPORTING,
        bio_direction=SupportDirection.CONTRADICTING,
        include_rates=True,
    )
    return c0, c1, c2


def test_three_cycle_cohort_tracks_persist_resolve_emerge_and_absence():
    c0, c1, c2 = _three_cycle_cohort()
    result = evaluate_replay_cohort(
        (c2, c0, c1),
        horizons=(2, 1),
    )

    rows = {
        (
            item.source_cycle_index,
            item.horizon_cycles,
            item.theme_id,
        ): item
        for item in result.transitions
    }

    dc_h1 = rows[(0, 1, "DataCenter_Infra")]
    assert (
        dc_h1.routing_intent
        is RoutingIntent.FORCED_FULL_REVIEW
    )
    assert (
        dc_h1.contradiction_transition
        is ContradictionTransition.PERSISTED
    )

    dc_h2 = rows[(0, 2, "DataCenter_Infra")]
    assert (
        dc_h2.contradiction_transition
        is ContradictionTransition.RESOLVED
    )

    bio_h2 = rows[(0, 2, "Genomics_Bio")]
    assert (
        bio_h2.routing_intent
        is RoutingIntent.ORDINARY_FULL_RESEARCH
    )
    assert (
        bio_h2.contradiction_transition
        is ContradictionTransition.EMERGED
    )

    rates_h1 = rows[(0, 1, "Rates")]
    assert rates_h1.future_presence is FuturePresence.NOT_PRESENT
    assert rates_h1.future_tier is None

    rates_h2 = rows[(0, 2, "Rates")]
    assert rates_h2.future_presence is FuturePresence.PRESENT
    assert (
        rates_h2.future_evidence_state.evidence_class
        is EvidenceClass.NO_INDEPENDENT
    )

    quiet_h1 = rows[(0, 1, "Quiet")]
    assert quiet_h1.future_presence is FuturePresence.PRESENT
    assert quiet_h1.future_replay_status is ReplayStatus.NO_OBSERVATION

    assert any(
        item.future_presence is FuturePresence.RIGHT_CENSORED
        for item in result.transitions
        if item.source_cycle_index > 0
    )


def test_three_cycle_cohort_emits_expected_summary_groups():
    result = evaluate_replay_cohort(
        _three_cycle_cohort(),
        horizons=(1, 2),
    )

    keys = {
        (item.routing_intent, item.horizon_cycles)
        for item in result.summaries
    }
    expected_intents = {
        RoutingIntent.FORCED_FULL_REVIEW,
        RoutingIntent.ORDINARY_FULL_RESEARCH,
        RoutingIntent.SCAN_ONLY,
        RoutingIntent.NO_OBSERVATION,
    }
    assert keys == {
        (intent, horizon)
        for intent in expected_intents
        for horizon in (1, 2)
    }


def test_summary_denominators_are_complete_partitions():
    result = evaluate_replay_cohort(
        _three_cycle_cohort(),
        horizons=(1, 2),
    )

    for summary in result.summaries:
        assert summary.source_n == (
            summary.future_cycle_available_n
            + summary.right_censored_n
        )
        assert summary.future_cycle_available_n == (
            summary.future_present_n
            + summary.future_not_present_n
        )
        assert summary.source_n == (
            summary.contradiction_unassessed_n
            + summary.contradiction_absent_n
            + summary.contradiction_emerged_n
            + summary.contradiction_persisted_n
            + summary.contradiction_resolved_n
        )
        assert summary.source_n == (
            summary.tier_unassessed_n
            + summary.tier_same_n
            + summary.tier_escalated_n
            + summary.tier_deescalated_n
        )
        assert summary.source_n == (
            summary.forced_review_unassessed_n
            + summary.forced_review_inactive_n
            + summary.forced_review_emerged_n
            + summary.forced_review_persisted_n
            + summary.forced_review_resolved_n
        )
        assert summary.source_n == (
            summary.scanner_config_unassessed_n
            + summary.scanner_config_same_n
            + summary.scanner_config_changed_n
        )
        assert (
            summary.evidence_class_changed_n
            <= summary.evidence_class_comparable_n
        )


def test_summary_mean_counts_match_non_none_transition_deltas():
    result = evaluate_replay_cohort(
        _three_cycle_cohort(),
        horizons=(1,),
    )

    for summary in result.summaries:
        rows = [
            item
            for item in result.transitions
            if item.routing_intent is summary.routing_intent
            and item.horizon_cycles == summary.horizon_cycles
        ]

        priority = [
            item.priority_delta
            for item in rows
            if item.priority_delta is not None
        ]
        assert summary.priority_delta_n == len(priority)
        assert summary.mean_priority_delta == (
            None
            if not priority
            else pytest.approx(sum(priority) / len(priority))
        )

        confidence = [
            item.confidence_delta
            for item in rows
            if item.confidence_delta is not None
        ]
        assert summary.confidence_delta_n == len(confidence)
        assert summary.mean_confidence_delta == (
            None
            if not confidence
            else pytest.approx(sum(confidence) / len(confidence))
        )

        novelty = [
            item.novelty_delta
            for item in rows
            if item.novelty_delta is not None
        ]
        assert summary.novelty_delta_n == len(novelty)
        assert summary.mean_novelty_delta == (
            None
            if not novelty
            else pytest.approx(sum(novelty) / len(novelty))
        )


def test_cohort_hashes_are_deterministic_and_bind_records_and_horizons():
    c0, c1, c2 = _three_cycle_cohort()

    first = evaluate_replay_cohort(
        (c0, c1, c2),
        horizons=(2, 1),
    )
    second = evaluate_replay_cohort(
        (c2, c0, c1),
        horizons=(1, 2),
    )

    assert second == first

    changed_horizon = evaluate_replay_cohort(
        (c0, c1, c2),
        horizons=(1,),
    )
    assert changed_horizon.input_hash != first.input_hash

    changed_record = evaluate_replay_cohort(
        (c0, c1),
        horizons=(1, 2),
    )
    assert changed_record.input_hash != first.input_hash


def test_result_hash_binds_complete_cohort_output():
    result = evaluate_replay_cohort(
        _three_cycle_cohort(),
        horizons=(1, 2),
    )
    payload = {
        "schema_version": result.schema_version,
        "evaluation_scope": result.evaluation_scope,
        "horizons": list(result.horizons),
        "cycles": list(result.cycles),
        "archive_record_hashes": list(result.archive_record_hashes),
        "transitions": [asdict(x) for x in result.transitions],
        "summaries": [asdict(x) for x in result.summaries],
        "limitations": list(result.limitations),
        "input_hash": result.input_hash,
    }
    assert result.result_hash == canonical_hash(payload)


def test_replay_cohort_interfaces_are_publicly_importable():
    import decision_lab

    for name in (
        "EvidenceClass",
        "FuturePresence",
        "RoutingIntent",
        "ContradictionTransition",
        "TierTransition",
        "IndependentEvidenceState",
        "ReplayCohortTransition",
        "ReplayCohortSummary",
        "ReplayCohortResult",
        "evaluate_replay_cohort",
    ):
        assert getattr(decision_lab, name) is not None



def test_non_forced_allocation_cannot_claim_forced_capacity_exhausted():
    record = _registered_archive(
        themes=("FullTheme",),
        observations=(
            _independent(
                "FullTheme",
                "support",
                SupportDirection.SUPPORTING,
            ),
        ),
    )
    result = record.replay_result
    allocation = replace(
        result.allocations[0],
        allocation_reasons=(
            *result.allocations[0].allocation_reasons,
            "forced review capacity exhausted",
        ),
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
        match="unsupported forced-review allocation state",
    ):
        evaluate_replay_cohort((bad,), horizons=())


def test_cycle_timestamp_mismatch_is_rejected():
    record = _archive()
    result = record.replay_result
    scan = replace(
        result.scan_results[0],
        as_of="2026-09-18",
    )
    allocation = replace(
        result.allocations[0],
        source_scan_result_hash=canonical_hash(asdict(scan)),
    )
    theme_record = replace(
        result.theme_records[0],
        scan_result=scan,
        allocation=allocation,
    )
    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            scan_results=(scan,),
            allocations=(allocation,),
            theme_records=(theme_record,),
        )
    )

    with pytest.raises(ValueError, match="inconsistent replay theme record"):
        evaluate_replay_cohort((bad,), horizons=(1,))


def test_multiple_scanner_config_hashes_in_cycle_are_rejected():
    record = _registered_archive(
        themes=("ATheme", "BTheme"),
        observations=(
            _independent(
                "ATheme",
                "a",
                SupportDirection.SUPPORTING,
            ),
            _independent(
                "BTheme",
                "b",
                SupportDirection.SUPPORTING,
            ),
        ),
    )
    result = record.replay_result
    scans = list(result.scan_results)
    scans[1] = replace(scans[1], config_hash="different")
    scan_by_theme = {item.theme_id: item for item in scans}
    allocations = []
    records = []
    for allocation in result.allocations:
        scan = scan_by_theme[allocation.theme_id]
        changed_allocation = replace(
            allocation,
            source_scan_result_hash=canonical_hash(asdict(scan)),
        )
        allocations.append(changed_allocation)
    allocation_by_theme = {
        item.theme_id: item for item in allocations
    }
    for theme_record in result.theme_records:
        if theme_record.replay_status is ReplayStatus.ROUTED:
            records.append(
                replace(
                    theme_record,
                    scan_result=scan_by_theme[theme_record.theme_id],
                    allocation=allocation_by_theme[theme_record.theme_id],
                )
            )
        else:
            records.append(theme_record)

    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            scan_results=tuple(scans),
            allocations=tuple(allocations),
            theme_records=tuple(records),
        )
    )

    with pytest.raises(
        ValueError,
        match="multiple scanner config hashes in replay cycle",
    ):
        evaluate_replay_cohort((bad,), horizons=(1,))



def test_no_observation_cannot_have_current_observation():
    record = _registered_archive(
        themes=("Quiet",),
        observations=(),
    )
    result = record.replay_result
    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            combined_observations=(_radar("Quiet"),),
        )
    )

    with pytest.raises(ValueError, match="inconsistent replay theme record"):
        evaluate_replay_cohort((bad,), horizons=())


def test_routed_theme_requires_current_observation():
    record = _archive()
    result = record.replay_result
    bad = _archive_from_semantically_modified_result(
        replace(result, combined_observations=())
    )

    with pytest.raises(ValueError, match="inconsistent replay theme record"):
        evaluate_replay_cohort((bad,), horizons=())


def _market_ready_archive():
    theme = "MarketTheme"
    package = _package(theme)
    ticker = f"{theme[:3].upper()}1"
    bars = tuple(
        MarketBar(
            symbol=symbol,
            session_date=session,
            available_at=f"{session}T21:00:00+00:00",
            close=close,
        )
        for symbol, closes in (
            ("SPY", (100, 100, 100)),
            (ticker, (100, 100, 103)),
        )
        for session, close in zip(
            ("2026-09-17", "2026-09-18", "2026-09-19"),
            closes,
            strict=True,
        )
    )
    theme_input = ThemeReplayInput(
        package=package,
        market_spec=MarketObservationSpec(
            theme_id=theme,
            mode=MarketObservationMode.BASKET,
            benchmark="SPY",
            current_return_sessions=1,
            prior_return_sessions=1,
            min_basket_members=1,
            version="test",
        ),
        market_config=MarketObservationConfig(),
        bars=bars,
        market_source_ref="fixture:market-ready",
    )
    result = run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of="2026-09-19",
            themes=(theme_input,),
            external_observations=(_radar(theme),),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
    return build_replay_archive_record(result)


def test_market_batch_observations_must_reach_combined_observations():
    record = _market_ready_archive()
    result = record.replay_result
    assert result.market_batches[0].observations

    market_observations = set(result.market_batches[0].observations)
    remaining = tuple(
        observation
        for observation in result.combined_observations
        if observation not in market_observations
    )
    assert remaining

    bad = _archive_from_semantically_modified_result(
        replace(result, combined_observations=remaining)
    )

    with pytest.raises(ValueError, match="inconsistent replay theme record"):
        evaluate_replay_cohort((bad,), horizons=())


def test_unregistered_forced_review_cannot_claim_capacity_exhaustion():
    record = _archive(
        observations=(
            _independent(
                "UnknownRisk",
                "unknown:risk",
                SupportDirection.CONTRADICTING,
            ),
        )
    )
    result = record.replay_result
    allocation = replace(
        result.allocations[0],
        allocation_reasons=(
            *result.allocations[0].allocation_reasons,
            "forced review capacity exhausted",
        ),
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
        match="unsupported forced-review allocation state",
    ):
        evaluate_replay_cohort((bad,), horizons=())


def test_unregistered_theme_cannot_receive_research_tier():
    record = _archive()
    result = record.replay_result
    allocation = replace(
        result.allocations[0],
        tier=ResearchTier.FULL_DECISION_RESEARCH,
        allocation_reasons=("full research gates satisfied",),
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
        match="unsupported unregistered allocation state",
    ):
        evaluate_replay_cohort((bad,), horizons=())
