from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime

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


def _package(
    theme="TestTheme",
    *,
    lifecycle=ThemeLifecycleState.STRENGTHENING,
    effective_from="2026-01-01",
    effective_to=None,
    source_path="fixture-a",
    generated_at="2026-09-19T00:00:00Z",
):
    universe = ThemeUniverse(
        theme=theme,
        version="u1",
        generated_at=generated_at,
    )
    universe.add_layer(ThemeLayer("layer", "display description"))
    universe.add_candidate(
        Candidate(
            ticker="AAA",
            theme=theme,
            layer="layer",
            membership_state="discovery",
            expression_role="quality_alpha",
            economic_exposure=0.8,
            evidence_strength=0.7,
            effective_from="2026-01-01",
            provenance=("fixture:aaa",),
            notes="annotation",
        )
    )
    return ThemePackage(
        definition=ThemeDefinition(
            theme_id=theme,
            display_name=f"{theme} Display",
            lifecycle_state=lifecycle,
            effective_from=effective_from,
            effective_to=effective_to,
            thesis_summary="display thesis",
            provenance=("fixture:definition",),
            version="1",
        ),
        universe=universe,
        theme_key_policy=ThemeKeyPolicy(),
        evidence_adapter="generic",
        version="p1",
        source_path=source_path,
    )


def _spec(theme="TestTheme"):
    return MarketObservationSpec(
        theme_id=theme,
        mode=MarketObservationMode.BASKET,
        benchmark="SPY",
        proxies=(),
        current_return_sessions=1,
        prior_return_sessions=1,
        min_basket_members=1,
        version="test",
    )


def _bar(symbol, session_date, close):
    return MarketBar(
        symbol=symbol,
        session_date=session_date,
        available_at=f"{session_date}T21:00:00+00:00",
        close=close,
    )


def _theme_input(package=None, bars=()):
    package = package or _package()
    return ThemeReplayInput(
        package=package,
        market_spec=_spec(package.definition.theme_id),
        market_config=MarketObservationConfig(),
        bars=tuple(bars),
        market_source_ref="fixture:market",
    )


def _cycle(**changes):
    payload = dict(
        cycle_as_of="2026-09-19",
        themes=(),
        external_observations=(),
        prior_scan_results=(),
        prior_allocations=(),
        scanner_config=ScannerConfig(),
        budget_config=ResearchBudgetConfig(),
    )
    payload.update(changes)
    return ReplayCycleInput(**payload)


def test_empty_replay_is_valid_and_deterministic():
    first = run_replay_cycle(_cycle())
    second = run_replay_cycle(_cycle())

    assert first == second
    assert first.market_batches == ()
    assert first.combined_observations == ()
    assert first.scan_results == ()
    assert first.allocations == ()
    assert first.theme_records == ()
    assert len(first.input_hash) == 64
    assert len(first.result_hash) == 64


def test_duplicate_registered_theme_is_rejected_before_adapter_execution():
    package = _package()
    theme_input = _theme_input(package)

    with pytest.raises(ValueError, match="duplicate replay theme"):
        run_replay_cycle(
            _cycle(themes=(theme_input, theme_input))
        )


@pytest.mark.parametrize(
    ("cycle_as_of", "effective_from"),
    [
        ("2026-09-19", "2026-09-20"),
        ("2026-09-19T23:30:00-04:00", "2026-09-21"),
    ],
)
def test_future_package_is_rejected_at_utc_cycle_date(
    cycle_as_of,
    effective_from,
):
    package = _package(effective_from=effective_from)

    with pytest.raises(
        ValueError,
        match="theme package not effective at cycle_as_of",
    ):
        run_replay_cycle(
            _cycle(
                cycle_as_of=cycle_as_of,
                themes=(_theme_input(package),),
            )
        )


def test_package_effective_to_is_half_open():
    package = _package(
        effective_from="2026-01-01",
        effective_to="2026-09-19",
    )

    with pytest.raises(
        ValueError,
        match="theme package not effective at cycle_as_of",
    ):
        run_replay_cycle(
            _cycle(themes=(_theme_input(package),))
        )


def test_offset_aware_cycle_uses_utc_date_for_package_activation():
    package = _package(effective_from="2026-09-20")

    result = run_replay_cycle(
        _cycle(
            cycle_as_of="2026-09-19T23:30:00-04:00",
            themes=(_theme_input(package),),
        )
    )

    assert result.theme_records[0].theme_id == "TestTheme"
    assert result.theme_records[0].replay_status is ReplayStatus.NO_OBSERVATION


def test_invalid_theme_package_effective_date_fails_closed():
    package = _package(effective_from="not-a-date")

    with pytest.raises(
        ValueError,
        match="invalid theme package effective date",
    ):
        run_replay_cycle(
            _cycle(themes=(_theme_input(package),))
        )


def test_market_source_ref_must_be_nonempty():
    package = _package()
    bad = replace(
        _theme_input(package),
        market_source_ref="   ",
    )

    with pytest.raises(ValueError, match="market_source_ref must be non-empty"):
        run_replay_cycle(_cycle(themes=(bad,)))


def test_prior_history_alone_does_not_create_current_theme_record():
    from decision_lab.research_budget import ResearchAllocation, ResearchTier
    from decision_lab.scanner import ThemeScanResult

    prior_scan = ThemeScanResult(
        theme_id="OldTheme",
        as_of="2026-09-18",
        discovery_score=0.5,
        structural_score=0.5,
        persistence_score=0.5,
        breadth_score=0.5,
        relative_strength_score=0.5,
        novelty_score=0.5,
        evidence_confidence=0.5,
        independent_support_count=1,
        independent_contradiction_count=0,
        lifecycle_recommendation="no_change",
        research_priority=0.5,
        forced_review=False,
        forced_review_severity=0,
        forced_review_reasons=(),
        reasons=(),
        evidence_refs=("prior",),
        config_hash="prior",
        registry_version=None,
        prior_result_refs=(),
    )
    prior_allocation = ResearchAllocation(
        theme_id="OldTheme",
        as_of="2026-09-18",
        tier=ResearchTier.SCAN_ONLY,
        scan_priority=0.5,
        effective_priority=0.5,
        scan_novelty_score=0.5,
        forced_review=False,
        allocation_reasons=("prior",),
        source_scan_result_hash="prior",
    )

    result = run_replay_cycle(
        _cycle(
            prior_scan_results=(prior_scan,),
            prior_allocations=(prior_allocation,),
        )
    )

    assert result.theme_records == ()



def _three_sessions():
    return ("2026-09-17", "2026-09-18", "2026-09-19")


def _coverage_pending_theme_input(theme="QuietTheme"):
    package = _package(theme=theme)
    spec = MarketObservationSpec(
        theme_id=theme,
        mode=MarketObservationMode.BASKET,
        benchmark="SPY",
        current_return_sessions=1,
        prior_return_sessions=1,
        min_basket_members=1,
        version="test",
    )
    return ThemeReplayInput(
        package=package,
        market_spec=spec,
        market_config=MarketObservationConfig(),
        bars=(_bar("SPY", "2026-09-19", 100),),
        market_source_ref=f"fixture:{theme}",
    )


def _radar_observation(theme, *, discovery=0.8, novelty=0.6):
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


def test_registered_coverage_pending_without_external_evidence_is_no_observation():
    result = run_replay_cycle(
        _cycle(themes=(_coverage_pending_theme_input(),))
    )

    record = result.theme_records[0]
    assert record.theme_id == "QuietTheme"
    assert record.registered
    assert record.market_batch is not None
    assert record.market_batch.observations == ()
    assert record.scan_result is None
    assert record.allocation is None
    assert record.replay_status is ReplayStatus.NO_OBSERVATION
    assert result.scan_results == ()
    assert result.allocations == ()


def test_registered_coverage_pending_with_model_evidence_is_routed_scan_only():
    theme_input = _coverage_pending_theme_input()
    result = run_replay_cycle(
        _cycle(
            themes=(theme_input,),
            external_observations=(_radar_observation("QuietTheme"),),
        )
    )

    record = result.theme_records[0]
    assert record.registered
    assert record.replay_status is ReplayStatus.ROUTED
    assert record.scan_result is not None
    assert record.allocation is not None
    assert record.allocation.tier is ResearchTier.SCAN_ONLY


def test_unknown_model_only_theme_is_real_scan_only_not_no_observation():
    result = run_replay_cycle(
        _cycle(
            external_observations=(_radar_observation("Rates"),),
        )
    )

    record = result.theme_records[0]
    assert record.theme_id == "Rates"
    assert not record.registered
    assert record.market_batch is None
    assert record.scan_result is not None
    assert record.allocation is not None
    assert record.allocation.tier is ResearchTier.SCAN_ONLY
    assert record.replay_status is ReplayStatus.ROUTED


def test_market_as_of_can_precede_cycle_as_of_while_allocation_uses_cycle():
    package = _package()
    spec = MarketObservationSpec(
        theme_id="TestTheme",
        mode=MarketObservationMode.BASKET,
        benchmark="SPY",
        current_return_sessions=1,
        prior_return_sessions=1,
        min_basket_members=1,
        version="test",
    )
    bars = (
        _bar("SPY", "2026-09-16", 100),
        _bar("SPY", "2026-09-17", 100),
        _bar("SPY", "2026-09-18", 100),
        _bar("AAA", "2026-09-16", 100),
        _bar("AAA", "2026-09-17", 100),
        _bar("AAA", "2026-09-18", 103),
    )
    theme_input = ThemeReplayInput(
        package=package,
        market_spec=spec,
        market_config=MarketObservationConfig(),
        bars=bars,
        market_source_ref="fixture:weekend",
    )

    result = run_replay_cycle(
        _cycle(
            cycle_as_of="2026-09-19",
            themes=(theme_input,),
        )
    )

    assert result.market_batches[0].market_as_of == "2026-09-18"
    assert result.combined_observations[0].as_of == "2026-09-18"
    assert result.allocations[0].as_of == "2026-09-19"


def test_external_future_observation_error_propagates_from_scanner():
    future = replace(
        _radar_observation("Rates"),
        as_of="2026-09-20",
    )

    with pytest.raises(ValueError, match="future-dated observation"):
        run_replay_cycle(
            _cycle(external_observations=(future,))
        )


def test_future_prior_allocation_error_propagates_from_allocator():
    from decision_lab.research_budget import ResearchAllocation

    future_prior = ResearchAllocation(
        theme_id="Rates",
        as_of="2026-09-20",
        tier=ResearchTier.SCAN_ONLY,
        scan_priority=0.5,
        effective_priority=0.5,
        scan_novelty_score=0.2,
        forced_review=False,
        allocation_reasons=("prior",),
        source_scan_result_hash="prior",
    )

    with pytest.raises(
        ValueError,
        match="prior research allocation must be strictly earlier",
    ):
        run_replay_cycle(
            _cycle(
                external_observations=(_radar_observation("Rates"),),
                prior_allocations=(future_prior,),
            )
        )



def _ready_theme_input(
    *,
    package=None,
    source_path=None,
    generated_at=None,
    used_end_close=103,
    extra_bars=(),
):
    package = package or _package(
        source_path=source_path or "fixture-a",
        generated_at=generated_at or "2026-09-19T00:00:00Z",
    )
    bars = (
        _bar("SPY", "2026-09-17", 100),
        _bar("SPY", "2026-09-18", 100),
        _bar("SPY", "2026-09-19", 100),
        _bar("AAA", "2026-09-17", 100),
        _bar("AAA", "2026-09-18", 100),
        _bar("AAA", "2026-09-19", used_end_close),
        *extra_bars,
    )
    return ThemeReplayInput(
        package=package,
        market_spec=_spec(package.definition.theme_id),
        market_config=MarketObservationConfig(),
        bars=tuple(bars),
        market_source_ref="fixture:semantic-hash",
    )


def _replace_candidate(package, **changes):
    copied = deepcopy(package)
    original = copied.universe.candidates["AAA"]
    copied.universe.candidates["AAA"] = replace(original, **changes)
    return copied


def _prior_scan(theme, as_of, *, priority=0.5):
    from decision_lab.scanner import ThemeScanResult

    return ThemeScanResult(
        theme_id=theme,
        as_of=as_of,
        discovery_score=0.5,
        structural_score=0.5,
        persistence_score=0.5,
        breadth_score=0.5,
        relative_strength_score=0.5,
        novelty_score=0.1,
        evidence_confidence=0.5,
        independent_support_count=1,
        independent_contradiction_count=0,
        lifecycle_recommendation="no_change",
        research_priority=priority,
        forced_review=False,
        forced_review_severity=0,
        forced_review_reasons=(),
        reasons=(),
        evidence_refs=(f"prior:{theme}",),
        config_hash="prior",
        registry_version=None,
        prior_result_refs=(),
    )


def _prior_allocation(theme, as_of, *, effective_priority=0.5):
    from decision_lab.research_budget import ResearchAllocation

    return ResearchAllocation(
        theme_id=theme,
        as_of=as_of,
        tier=ResearchTier.SCAN_ONLY,
        scan_priority=0.5,
        effective_priority=effective_priority,
        scan_novelty_score=0.1,
        forced_review=False,
        allocation_reasons=("prior",),
        source_scan_result_hash=f"prior:{theme}",
    )


def test_input_order_is_semantically_irrelevant():
    a = _ready_theme_input(package=_package(theme="A"))
    b = _ready_theme_input(package=_package(theme="B"))
    oa = _radar_observation("UnknownA")
    ob = _radar_observation("UnknownB")

    first = run_replay_cycle(
        _cycle(
            themes=(a, b),
            external_observations=(oa, ob),
        )
    )
    second = run_replay_cycle(
        _cycle(
            themes=(b, a),
            external_observations=(ob, oa),
        )
    )

    assert second == first


def test_prior_history_order_is_semantically_irrelevant():
    current = _radar_observation("Rates")
    scan_a = _prior_scan("A", "2026-09-17")
    scan_b = _prior_scan("B", "2026-09-18")
    allocation_a = _prior_allocation("A", "2026-09-17")
    allocation_b = _prior_allocation("B", "2026-09-18")

    first = run_replay_cycle(
        _cycle(
            external_observations=(current,),
            prior_scan_results=(scan_a, scan_b),
            prior_allocations=(allocation_a, allocation_b),
        )
    )
    second = run_replay_cycle(
        _cycle(
            external_observations=(current,),
            prior_scan_results=(scan_b, scan_a),
            prior_allocations=(allocation_b, allocation_a),
        )
    )

    assert second == first
    assert second.input_hash == first.input_hash
    assert second.result_hash == first.result_hash


def test_reversing_raw_bar_order_does_not_change_hashes():
    theme_input = _ready_theme_input()
    reversed_input = replace(
        theme_input,
        bars=tuple(reversed(theme_input.bars)),
    )

    first = run_replay_cycle(_cycle(themes=(theme_input,)))
    second = run_replay_cycle(_cycle(themes=(reversed_input,)))

    assert second.input_hash == first.input_hash
    assert second.result_hash == first.result_hash
    assert second == first


def test_unrelated_unused_bar_does_not_change_replay_hash():
    first_input = _ready_theme_input()
    second_input = _ready_theme_input(
        extra_bars=(
            MarketBar(
                symbol="UNUSED",
                session_date="bad-date",
                available_at="2099-01-01",
                close=-1,
            ),
        )
    )

    first = run_replay_cycle(_cycle(themes=(first_input,)))
    second = run_replay_cycle(_cycle(themes=(second_input,)))

    assert second.input_hash == first.input_hash
    assert second.result_hash == first.result_hash


def test_generated_at_and_source_path_do_not_change_input_hash():
    first = run_replay_cycle(
        _cycle(
            themes=(
                _ready_theme_input(
                    package=_package(
                        source_path="path-a",
                        generated_at="2026-09-19T00:00:00Z",
                    )
                ),
            )
        )
    )
    second = run_replay_cycle(
        _cycle(
            themes=(
                _ready_theme_input(
                    package=_package(
                        source_path="path-b",
                        generated_at="2099-01-01T00:00:00Z",
                    )
                ),
            )
        )
    )

    assert second.input_hash == first.input_hash
    assert second.result_hash == first.result_hash


def test_candidate_annotation_only_changes_do_not_change_input_hash():
    base = _package()
    annotated = _replace_candidate(
        base,
        notes="different note",
        expression_role="beta_proxy",
        economic_exposure=0.1,
        evidence_strength=0.2,
    )

    first = run_replay_cycle(
        _cycle(themes=(_ready_theme_input(package=base),))
    )
    second = run_replay_cycle(
        _cycle(themes=(_ready_theme_input(package=annotated),))
    )

    assert second.input_hash == first.input_hash


def test_definition_display_annotations_do_not_change_input_hash():
    base = _package()
    changed_definition = replace(
        base.definition,
        display_name="Different display",
        thesis_summary="Different prose",
    )
    changed = replace(base, definition=changed_definition)

    first = run_replay_cycle(
        _cycle(themes=(_ready_theme_input(package=base),))
    )
    second = run_replay_cycle(
        _cycle(themes=(_ready_theme_input(package=changed),))
    )

    assert second.input_hash == first.input_hash


@pytest.mark.parametrize(
    "mutation",
    [
        "used_bar",
        "candidate_effective_from",
        "candidate_provenance",
        "definition_lifecycle",
        "definition_effective_from",
        "definition_provenance",
        "scanner_config",
        "budget_config",
        "external_observation",
        "prior_allocation_history",
    ],
)
def test_semantic_changes_move_replay_input_hash(mutation):
    base_theme = _ready_theme_input()
    kwargs = {"themes": (base_theme,)}

    if mutation == "used_bar":
        kwargs["themes"] = (_ready_theme_input(used_end_close=120),)
    elif mutation == "candidate_effective_from":
        changed = _replace_candidate(
            base_theme.package,
            effective_from="2026-09-18",
        )
        kwargs["themes"] = (_ready_theme_input(package=changed),)
    elif mutation == "candidate_provenance":
        changed = _replace_candidate(
            base_theme.package,
            provenance=("different:provenance",),
        )
        kwargs["themes"] = (_ready_theme_input(package=changed),)
    elif mutation == "definition_lifecycle":
        changed = replace(
            base_theme.package,
            definition=replace(
                base_theme.package.definition,
                lifecycle_state=ThemeLifecycleState.MATURE,
            ),
        )
        kwargs["themes"] = (_ready_theme_input(package=changed),)
    elif mutation == "definition_effective_from":
        changed = replace(
            base_theme.package,
            definition=replace(
                base_theme.package.definition,
                effective_from="2025-12-31",
            ),
        )
        kwargs["themes"] = (_ready_theme_input(package=changed),)
    elif mutation == "definition_provenance":
        changed = replace(
            base_theme.package,
            definition=replace(
                base_theme.package.definition,
                provenance=("different:definition",),
            ),
        )
        kwargs["themes"] = (_ready_theme_input(package=changed),)
    elif mutation == "scanner_config":
        kwargs["scanner_config"] = replace(
            ScannerConfig(),
            stale_after_days=7,
        )
    elif mutation == "budget_config":
        kwargs["budget_config"] = replace(
            ResearchBudgetConfig(),
            theme_research_slots=7,
        )
    elif mutation == "external_observation":
        kwargs["external_observations"] = (
            _radar_observation("Rates", discovery=0.9),
        )
    elif mutation == "prior_allocation_history":
        kwargs["prior_allocations"] = (
            _prior_allocation(
                "TestTheme",
                "2026-09-18",
                effective_priority=0.6,
            ),
        )

    baseline = run_replay_cycle(
        _cycle(themes=(base_theme,))
    )
    changed = run_replay_cycle(_cycle(**kwargs))

    assert changed.input_hash != baseline.input_hash


def test_result_hash_binds_output_not_only_input_hash():
    result = run_replay_cycle(
        _cycle(themes=(_ready_theme_input(),))
    )

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

    assert result.result_hash == canonical_hash(payload)
