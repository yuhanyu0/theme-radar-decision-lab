from dataclasses import replace

import pytest

from decision_lab.market_observation import (
    MarketBar,
    MarketObservationConfig,
    MarketObservationMode,
    MarketObservationSpec,
    MarketObservationStatus,
    adapt_market_observations,
)
from decision_lab.themes import ThemeDefinition, ThemeKeyPolicy, ThemePackage
from decision_lab.universe import ThemeLayer, ThemeUniverse


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

    with pytest.raises(ValueError, match="normalization scales must be positive"):
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
