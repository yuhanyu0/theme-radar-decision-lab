from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

import pytest

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
from decision_lab.research_budget import ResearchBudgetConfig
from decision_lab.scanner import ScannerConfig
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
