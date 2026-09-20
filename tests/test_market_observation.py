from dataclasses import asdict, replace
from pathlib import Path

import pytest

from decision_lab.ledger import canonical_hash
from decision_lab.market_observation import (
    MarketBar,
    MarketObservationConfig,
    MarketObservationMode,
    MarketObservationSpec,
    MarketObservationStatus,
    adapt_market_observations,
    load_market_observation_config,
    load_market_observation_spec,
)
from decision_lab.scanner import ScannerConfig, SupportDirection, rank_themes
from decision_lab.themes import (
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemePackage,
    load_theme_package,
)
from decision_lab.universe import Candidate, ThemeLayer, ThemeUniverse


def _package(theme="DataCenter_Infra", candidates=()):
    universe = ThemeUniverse(theme=theme, version="fixture-u1")
    universe.add_layer(ThemeLayer("layer"))
    for candidate in candidates:
        universe.add_candidate(candidate)
    return ThemePackage(
        definition=ThemeDefinition(
            theme_id=theme,
            display_name=theme,
            effective_from="2026-01-01",
            version="fixture-t1",
        ),
        universe=universe,
        theme_key_policy=ThemeKeyPolicy(),
        evidence_adapter="generic",
        version="fixture-p1",
        source_path="fixture",
    )


def _bar(symbol, session_date, close, *, available_at=None):
    return MarketBar(
        symbol=symbol,
        session_date=session_date,
        available_at=available_at or f"{session_date}T21:00:00+00:00",
        close=close,
    )


def _basket_spec():
    return MarketObservationSpec(
        theme_id="DataCenter_Infra",
        mode=MarketObservationMode.BASKET,
        benchmark="SPY",
        proxies=(),
        current_return_sessions=2,
        prior_return_sessions=2,
        min_basket_members=2,
        version="test",
    )


def test_market_bar_rejects_nonpositive_or_nonfinite_close():
    with pytest.raises(ValueError, match="close must be finite and positive"):
        _bar("SPY", "2026-09-18", 0.0).validate()

    with pytest.raises(ValueError, match="close must be finite and positive"):
        _bar("SPY", "2026-09-18", float("nan")).validate()


def test_market_bar_rejects_invalid_session_date():
    with pytest.raises(ValueError, match="invalid session_date"):
        _bar("SPY", "not-a-date", 100.0).validate()


def test_date_only_cycle_accepts_same_day_available_bar_and_rejects_next_day():
    package = _package()
    bars = [
        _bar("SPY", "2026-09-15", 99),
        _bar("SPY", "2026-09-16", 100),
        _bar("SPY", "2026-09-17", 101),
        _bar("SPY", "2026-09-18", 102),
        _bar("SPY", "2026-09-19", 103, available_at="2026-09-19T16:00:00+00:00"),
    ]

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-19",
        market_source_ref="fixture:bars",
    )
    assert batch.market_as_of == "2026-09-19"

    future = list(bars)
    future[-1] = _bar(
        "SPY",
        "2026-09-19",
        103,
        available_at="2026-09-20T00:00:00+00:00",
    )
    with pytest.raises(ValueError, match="required bar available after cycle_as_of"):
        adapt_market_observations(
            package=package,
            bars=future,
            spec=_basket_spec(),
            config=MarketObservationConfig(),
            cycle_as_of="2026-09-19",
            market_source_ref="fixture:bars",
        )


def test_duplicate_used_symbol_session_is_rejected():
    package = _package()
    bars = [
        _bar("SPY", "2026-09-15", 99),
        _bar("SPY", "2026-09-16", 100),
        _bar("SPY", "2026-09-16", 100),
        _bar("SPY", "2026-09-17", 101),
        _bar("SPY", "2026-09-18", 102),
        _bar("SPY", "2026-09-19", 103),
    ]

    with pytest.raises(ValueError, match="duplicate symbol/session_date"):
        adapt_market_observations(
            package=package,
            bars=bars,
            spec=_basket_spec(),
            config=MarketObservationConfig(),
            cycle_as_of="2026-09-19",
            market_source_ref="fixture:bars",
        )


def test_unused_bad_symbol_is_ignored_before_validation():
    package = _package()
    bars = [
        _bar("SPY", "2026-09-15", 99),
        _bar("SPY", "2026-09-16", 100),
        _bar("SPY", "2026-09-17", 101),
        _bar("SPY", "2026-09-18", 102),
        _bar("SPY", "2026-09-19", 103),
        MarketBar(
            symbol="UNUSED",
            session_date="bad-date",
            available_at="2099-01-01T00:00:00+00:00",
            close=-1,
        ),
    ]

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-19",
        market_source_ref="fixture:bars",
    )

    assert batch.market_as_of == "2026-09-19"


def test_theme_mismatch_and_invalid_spec_are_rejected():
    package = _package()

    with pytest.raises(ValueError, match="spec theme does not match package"):
        adapt_market_observations(
            package=package,
            bars=[],
            spec=replace(_basket_spec(), theme_id="Other"),
            config=MarketObservationConfig(),
            cycle_as_of="2026-09-19",
            market_source_ref="fixture:bars",
        )

    with pytest.raises(ValueError, match="proxy mode requires at least one proxy"):
        MarketObservationSpec(
            theme_id="Genomics_Bio",
            mode=MarketObservationMode.PROXY,
            benchmark="SPY",
            proxies=(),
        ).validate()

    with pytest.raises(ValueError, match="duplicate proxies"):
        MarketObservationSpec(
            theme_id="Genomics_Bio",
            mode=MarketObservationMode.PROXY,
            benchmark="SPY",
            proxies=("ARKG", "arkg"),
        ).validate()

    with pytest.raises(ValueError, match="proxy cannot equal benchmark"):
        MarketObservationSpec(
            theme_id="Genomics_Bio",
            mode=MarketObservationMode.PROXY,
            benchmark="SPY",
            proxies=("SPY",),
        ).validate()

    with pytest.raises(
        ValueError,
        match="normalization scales must be finite and positive",
    ):
        replace(MarketObservationConfig(), novelty_scale=0.0).validate()


def test_insufficient_benchmark_history_returns_coverage_pending():
    package = _package()
    batch = adapt_market_observations(
        package=package,
        bars=[_bar("SPY", "2026-09-19", 100)],
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-19",
        market_source_ref="fixture:bars",
    )

    assert batch.observations == ()
    assert len(batch.diagnostics) == 1
    assert batch.diagnostics[0].status is MarketObservationStatus.COVERAGE_PENDING
    assert "insufficient benchmark history" in batch.diagnostics[0].reason



def _candidate(ticker, *, effective_from=None, effective_to=None):
    return Candidate(
        ticker=ticker,
        theme="DataCenter_Infra",
        layer="layer",
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _sessions():
    return [
        "2026-09-09",
        "2026-09-10",
        "2026-09-11",
        "2026-09-14",
        "2026-09-15",
    ]


def _series(symbol, closes, *, available_hour=21):
    return [
        _bar(
            symbol,
            session,
            close,
            available_at=f"{session}T{available_hour:02d}:00:00+00:00",
        )
        for session, close in zip(_sessions(), closes, strict=True)
    ]


def test_basket_current_return_breadth_persistence_and_excess_are_exact():
    package = _package(
        candidates=[
            _candidate("A", effective_from="2026-01-01"),
            _candidate("B", effective_from="2026-01-01"),
        ]
    )
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("A", [100, 100, 100, 90, 80])
        + _series("B", [100, 100, 100, 100, 90])
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:basket",
    )
    diag = batch.diagnostics[0]

    assert diag.status is MarketObservationStatus.READY
    assert diag.current_member_symbols == ("A", "B")
    assert diag.current_return == pytest.approx((-0.20 - 0.10) / 2)
    assert diag.benchmark_current_return == 0.0
    assert diag.current_excess_return == pytest.approx(-0.15)
    assert diag.breadth == 0.0
    assert diag.persistence == 0.0
    assert diag.relative_strength_signal == pytest.approx(0.0)
    assert diag.breadth_signal == 0.0
    assert diag.persistence_signal == 0.0
    assert diag.support_direction is SupportDirection.CONTRADICTING
    assert len(batch.observations) == 1


def test_strong_broad_basket_is_supporting():
    package = _package(
        candidates=[
            _candidate("A", effective_from="2026-01-01"),
            _candidate("B", effective_from="2026-01-01"),
        ]
    )
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("A", [100, 100, 100, 105, 110])
        + _series("B", [100, 100, 100, 104, 108])
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:basket",
    )

    assert batch.diagnostics[0].current_excess_return > 0.02
    assert batch.diagnostics[0].breadth == 1.0
    assert batch.diagnostics[0].support_direction is SupportDirection.SUPPORTING


def test_mixed_basket_is_neutral():
    package = _package(
        candidates=[
            _candidate("A", effective_from="2026-01-01"),
            _candidate("B", effective_from="2026-01-01"),
        ]
    )
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("A", [100, 100, 100, 101, 102])
        + _series("B", [100, 100, 100, 99, 98])
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:basket",
    )

    assert batch.diagnostics[0].support_direction is SupportDirection.NEUTRAL


def test_member_admitted_after_window_start_is_excluded_from_current_basket():
    package = _package(
        candidates=[
            _candidate("A", effective_from="2026-01-01"),
            _candidate("NEW", effective_from="2026-09-15"),
        ]
    )
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("A", [100, 100, 100, 100, 105])
        + _series("NEW", [100, 100, 100, 100, 200])
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=replace(_basket_spec(), min_basket_members=1),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:basket",
    )

    assert batch.diagnostics[0].current_member_symbols == ("A",)
    assert batch.diagnostics[0].current_return == pytest.approx(0.05)


def test_membership_uses_session_date_not_available_at():
    package = _package(
        candidates=[
            _candidate("A", effective_from="2026-01-01"),
            _candidate("NEW", effective_from="2026-09-15"),
        ]
    )
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("A", [100, 100, 100, 100, 101])
        + [
            _bar(
                "NEW",
                session,
                close,
                available_at="2026-09-15T10:00:00+00:00",
            )
            for session, close in zip(
                _sessions(),
                [100, 100, 100, 100, 200],
                strict=True,
            )
        ]
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=replace(_basket_spec(), min_basket_members=1),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:basket",
    )

    assert batch.diagnostics[0].current_member_symbols == ("A",)


def test_invalid_rows_for_not_yet_effective_member_are_ignored():
    package = _package(
        candidates=[
            _candidate("A", effective_from="2026-01-01"),
            _candidate("FUTURE", effective_from="2026-10-01"),
        ]
    )
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("A", [100, 100, 100, 100, 101])
        + [
            MarketBar(
                symbol="FUTURE",
                session_date="bad-date",
                available_at="2099-01-01",
                close=-1,
            )
        ]
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=replace(_basket_spec(), min_basket_members=1),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:basket",
    )

    assert batch.diagnostics[0].current_member_symbols == ("A",)


def test_effective_to_is_half_open_on_session_date():
    package = _package(
        candidates=[
            _candidate("A", effective_from="2026-01-01"),
            _candidate(
                "OLD",
                effective_from="2026-01-01",
                effective_to="2026-09-15",
            ),
        ]
    )
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("A", [100, 100, 100, 100, 101])
        + _series("OLD", [100, 100, 100, 100, 200])
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=replace(_basket_spec(), min_basket_members=1),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:basket",
    )

    assert batch.diagnostics[0].current_member_symbols == ("A",)


def test_stable_cohort_not_current_composition_drives_novelty():
    package = _package(
        candidates=[
            _candidate("A", effective_from="2026-01-01"),
            _candidate("B", effective_from="2026-01-01"),
            _candidate("NEW", effective_from="2026-09-14"),
        ]
    )
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("A", [100, 100, 100, 110, 120])
        + _series("B", [100, 100, 100, 90, 80])
        + _series("NEW", [100, 100, 100, 100, 200])
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:basket",
    )
    diag = batch.diagnostics[0]

    assert diag.current_member_symbols == ("A", "B")
    assert diag.stable_member_symbols == ("A", "B")
    assert not diag.membership_changed
    assert diag.comparison_prior_excess_return == pytest.approx(0.0)
    assert diag.comparison_current_excess_return == pytest.approx(0.0)
    assert diag.novelty_abs_excess_change == pytest.approx(0.0)
    assert diag.novelty_signal == 0.0


def test_membership_changed_is_explicit_when_current_cohort_exceeds_stable_cohort():
    package = _package(
        candidates=[
            _candidate("A", effective_from="2026-01-01"),
            _candidate("B", effective_from="2026-09-11"),
        ]
    )
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("A", [100, 100, 100, 100, 100])
        + _series("B", [100, 100, 100, 110, 120])
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=replace(_basket_spec(), min_basket_members=1),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:basket",
    )
    diag = batch.diagnostics[0]

    assert diag.current_member_symbols == ("A", "B")
    assert diag.stable_member_symbols == ("A",)
    assert diag.membership_changed
    assert diag.current_excess_return == pytest.approx(0.10)
    assert diag.comparison_current_excess_return == pytest.approx(0.0)


def test_insufficient_stable_cohort_leaves_only_novelty_missing():
    package = _package(
        candidates=[
            _candidate("A", effective_from="2026-01-01"),
            _candidate("B", effective_from="2026-09-11"),
        ]
    )
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("A", [100, 100, 100, 100, 100])
        + _series("B", [100, 100, 100, 110, 120])
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:basket",
    )
    diag = batch.diagnostics[0]

    assert diag.status is MarketObservationStatus.READY
    assert diag.current_member_count == 2
    assert diag.stable_member_count == 1
    assert diag.novelty_signal is None
    assert "insufficient stable comparison cohort" in diag.warnings


def test_too_few_current_members_returns_coverage_pending_and_no_observation():
    package = _package(
        candidates=[_candidate("A", effective_from="2026-01-01")]
    )
    bars = _series("SPY", [100, 100, 100, 100, 100]) + _series(
        "A", [100, 100, 100, 100, 101]
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:basket",
    )

    assert batch.observations == ()
    assert batch.diagnostics[0].status is MarketObservationStatus.COVERAGE_PENDING
    assert "too few current basket members" in batch.diagnostics[0].reason



def _proxy_spec():
    return MarketObservationSpec(
        theme_id="Genomics_Bio",
        mode=MarketObservationMode.PROXY,
        benchmark="SPY",
        proxies=("ARKG", "XBI"),
        current_return_sessions=2,
        prior_return_sessions=2,
        min_basket_members=2,
        version="test",
    )


def test_proxy_mode_emits_supporting_and_neutral_observations_in_lexical_order():
    package = _package(theme="Genomics_Bio")
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("ARKG", [100, 100, 100, 110, 120])
        + _series("XBI", [100, 100, 100, 100.5, 101])
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_proxy_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:proxy",
    )

    assert [d.instrument for d in batch.diagnostics] == ["ARKG", "XBI"]
    assert [o.support_direction for o in batch.observations] == [
        SupportDirection.SUPPORTING,
        SupportDirection.NEUTRAL,
    ]
    assert all(d.breadth is None for d in batch.diagnostics)
    assert all(o.breadth_signal is None for o in batch.observations)


def test_negative_weak_proxy_is_contradicting():
    package = _package(theme="Genomics_Bio")
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("ARKG", [100, 100, 100, 95, 90])
    )
    spec = replace(_proxy_spec(), proxies=("ARKG",))

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=spec,
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:proxy",
    )

    assert batch.observations[0].support_direction is SupportDirection.CONTRADICTING


def test_one_missing_proxy_does_not_suppress_valid_proxy():
    package = _package(theme="Genomics_Bio")
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("ARKG", [100, 100, 100, 110, 120])
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_proxy_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:proxy",
    )

    assert [o.source_ref.split(":")[3] for o in batch.observations] == ["ARKG"]
    by_instrument = {d.instrument: d for d in batch.diagnostics}
    assert by_instrument["ARKG"].status is MarketObservationStatus.READY
    assert by_instrument["XBI"].status is MarketObservationStatus.COVERAGE_PENDING


def test_all_missing_proxies_emit_no_observations():
    package = _package(theme="Genomics_Bio")
    bars = _series("SPY", [100, 100, 100, 100, 100])

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_proxy_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:proxy",
    )

    assert batch.observations == ()
    assert all(
        d.status is MarketObservationStatus.COVERAGE_PENDING
        for d in batch.diagnostics
    )


def test_output_provenance_and_scanner_contract_are_directly_compatible():
    package = _package(theme="Genomics_Bio")
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("ARKG", [100, 100, 100, 110, 120])
    )
    spec = replace(_proxy_spec(), proxies=("ARKG",))

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=spec,
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:proxy",
    )
    observation = batch.observations[0]
    diag = batch.diagnostics[0]

    assert observation.source_type == "derived_feature"
    assert observation.is_independent
    assert observation.observed_or_inferred == "inferred"
    assert observation.source_ref.startswith(
        "market_observation:Genomics_Bio:proxy:ARKG:2026-09-15:"
    )
    assert "fixture:proxy" in observation.evidence_refs
    assert "proxy:ARKG" in observation.evidence_refs
    assert f"package:Genomics_Bio@{package.version}" in observation.evidence_refs
    assert f"universe:Genomics_Bio@{package.universe.version}" in observation.evidence_refs
    assert f"diagnostic:{diag.diagnostic_hash}" in observation.evidence_refs

    results = rank_themes(
        batch.observations,
        {"Genomics_Bio": package.definition},
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-15",
    )
    assert results[0].independent_support_count == 1


def test_input_order_and_unrelated_symbol_do_not_change_semantic_output_or_hash():
    package = _package(theme="Genomics_Bio")
    base = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("ARKG", [100, 100, 100, 110, 120])
    )
    spec = replace(_proxy_spec(), proxies=("ARKG",))

    first = adapt_market_observations(
        package=package,
        bars=base,
        spec=spec,
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:proxy",
    )
    second = adapt_market_observations(
        package=package,
        bars=list(reversed(base))
        + [
            MarketBar(
                symbol="UNRELATED",
                session_date="bad-date",
                available_at="2099-01-01",
                close=-100,
            )
        ],
        spec=spec,
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:proxy",
    )

    assert second == first


def test_source_level_and_batch_hashes_bind_only_used_bars():
    package = _package(theme="Genomics_Bio")
    bars = (
        _series("SPY", [100, 100, 100, 100, 100])
        + _series("ARKG", [100, 100, 100, 110, 120])
        + _series("XBI", [100, 100, 100, 100.5, 101])
    )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=_proxy_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:proxy",
    )

    source_hashes = sorted(d.input_hash for d in batch.diagnostics)
    assert batch.input_hash == canonical_hash(source_hashes)
    assert all(d.diagnostic_hash for d in batch.diagnostics)



ROOT = Path(__file__).resolve().parents[1]


def test_default_market_observation_config_matches_approved_contract():
    config = load_market_observation_config(
        ROOT / "config/adapters/market_observation_defaults.yaml"
    )

    assert config.version == "0.1"
    assert config.calibration_label == "uncalibrated"
    assert config.relative_strength_scale == 0.20
    assert config.novelty_scale == 0.10
    assert config.basket_contradiction_excess_max == -0.02
    assert config.basket_contradiction_breadth_max == 0.25
    assert config.proxy_support_excess_min == 0.02
    assert config.proxy_support_persistence_min == 0.60


def test_theme_market_observation_specs_load_exactly():
    dc = load_market_observation_spec(
        ROOT / "config/market_observations/datacenter_infra.yaml"
    )
    bio = load_market_observation_spec(
        ROOT / "config/market_observations/genomics_bio.yaml"
    )

    assert dc.mode is MarketObservationMode.BASKET
    assert dc.benchmark == "SPY"
    assert dc.proxies == ()

    assert bio.mode is MarketObservationMode.PROXY
    assert bio.benchmark == "SPY"
    assert bio.proxies == ("ARKG", "XBI")


def test_real_genomics_package_cannot_retroactively_form_five_session_basket():
    package = load_theme_package(ROOT / "config/themes/genomics_bio.yaml")
    config = MarketObservationConfig()
    spec = MarketObservationSpec(
        theme_id="Genomics_Bio",
        mode=MarketObservationMode.BASKET,
        benchmark="SPY",
        proxies=(),
        current_return_sessions=2,
        prior_return_sessions=2,
        min_basket_members=3,
        version="test",
    )
    sessions = [
        "2026-09-14",
        "2026-09-15",
        "2026-09-16",
        "2026-09-17",
        "2026-09-18",
    ]
    bars = [
        _bar("SPY", session, 100 + index)
        for index, session in enumerate(sessions)
    ]
    for symbol in ("CRSP", "BEAM", "NTLA", "ILMN"):
        bars.extend(
            _bar(symbol, session, 100 + index)
            for index, session in enumerate(sessions)
        )

    batch = adapt_market_observations(
        package=package,
        bars=bars,
        spec=spec,
        config=config,
        cycle_as_of="2026-09-18",
        market_source_ref="fixture:genomics-no-retro",
    )

    assert batch.observations == ()
    assert batch.diagnostics[0].status is MarketObservationStatus.COVERAGE_PENDING
    assert batch.diagnostics[0].current_member_count == 0


def test_adapter_does_not_mutate_theme_package_or_permission_state():
    from copy import deepcopy

    package = load_theme_package(ROOT / "config/themes/genomics_bio.yaml")
    before = deepcopy(package)
    policy_before = package.theme_key_policy

    sessions = [
        "2026-09-14",
        "2026-09-15",
        "2026-09-16",
        "2026-09-17",
        "2026-09-18",
    ]
    bars = [
        _bar("SPY", session, 100)
        for session in sessions
    ] + [
        _bar("ARKG", session, close)
        for session, close in zip(
            sessions,
            [100, 100, 100, 110, 120],
            strict=True,
        )
    ]
    spec = replace(
        load_market_observation_spec(
            ROOT / "config/market_observations/genomics_bio.yaml"
        ),
        current_return_sessions=2,
        prior_return_sessions=2,
        proxies=("ARKG",),
    )

    adapt_market_observations(
        package=package,
        bars=bars,
        spec=spec,
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-18",
        market_source_ref="fixture:no-mutation",
    )

    assert package == before
    assert package.theme_key_policy == policy_before


def test_market_observation_interfaces_are_publicly_importable():
    import decision_lab

    for name in (
        "MarketBar",
        "MarketObservationBatch",
        "MarketObservationConfig",
        "MarketObservationDiagnostics",
        "MarketObservationMode",
        "MarketObservationSpec",
        "MarketObservationStatus",
        "adapt_market_observations",
        "load_market_observation_config",
        "load_market_observation_spec",
    ):
        assert getattr(decision_lab, name) is not None



def test_string_mode_cannot_bypass_market_observation_mode_validation():
    spec = MarketObservationSpec(
        theme_id="Genomics_Bio",
        mode="proxy",
        benchmark="SPY",
        proxies=(),
    )

    with pytest.raises(TypeError, match="unsupported market observation mode"):
        spec.validate()


def test_basket_coverage_hash_binds_attempted_member_bars_and_final_diagnostic():
    package = _package(
        candidates=[_candidate("A", effective_from="2026-01-01")]
    )
    benchmark = _series("SPY", [100, 100, 100, 100, 100])
    first_bars = benchmark + _series("A", [100, 100, 100, 100, 101])
    second_bars = benchmark + _series("A", [100, 100, 100, 100, 150])

    first = adapt_market_observations(
        package=package,
        bars=first_bars,
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:coverage-hash",
    )
    second = adapt_market_observations(
        package=package,
        bars=second_bars,
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-15",
        market_source_ref="fixture:coverage-hash",
    )

    first_diag = first.diagnostics[0]
    second_diag = second.diagnostics[0]
    assert first_diag.status is MarketObservationStatus.COVERAGE_PENDING
    assert first_diag.current_member_symbols == ("A",)
    assert first_diag.input_hash != second_diag.input_hash
    assert first.input_hash != second.input_hash

    payload = asdict(first_diag)
    payload["diagnostic_hash"] = None
    assert first_diag.diagnostic_hash == canonical_hash(payload)
    assert f"package:DataCenter_Infra@{package.version}" in first_diag.evidence_refs
    assert (
        f"universe:DataCenter_Infra@{package.universe.version}"
        in first_diag.evidence_refs
    )



@pytest.mark.parametrize("bad_scale", [float("nan"), float("inf")])
def test_normalization_scales_must_be_finite_and_positive(bad_scale):
    config = replace(
        MarketObservationConfig(),
        relative_strength_scale=bad_scale,
    )

    with pytest.raises(
        ValueError,
        match="normalization scales must be finite and positive",
    ):
        config.validate()


def test_insufficient_benchmark_diagnostic_keeps_package_universe_provenance():
    package = _package()
    batch = adapt_market_observations(
        package=package,
        bars=[_bar("SPY", "2026-09-19", 100)],
        spec=_basket_spec(),
        config=MarketObservationConfig(),
        cycle_as_of="2026-09-19",
        market_source_ref="fixture:benchmark-short",
    )

    diagnostic = batch.diagnostics[0]
    assert "fixture:benchmark-short" in diagnostic.evidence_refs
    assert f"package:DataCenter_Infra@{package.version}" in diagnostic.evidence_refs
    assert (
        f"universe:DataCenter_Infra@{package.universe.version}"
        in diagnostic.evidence_refs
    )
