# Market Observation Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral MarketObservationAdapter that converts daily close bars plus effective-dated theme membership and declared proxies into replayable raw diagnostics and independent ThemeScanObservation records without changing scanner, budget, ThemeKey, Tape, router, or ledger semantics.

**Architecture:** Add one focused `market_observation.py` module. It owns bar/session validation, benchmark-defined windows, effective-dated BASKET and declared PROXY transforms, stable-cohort novelty, deterministic support-direction normalization, provenance hashes, and YAML loaders. It consumes existing `ThemePackage`, `Candidate.is_effective()`, `canonical_hash()`, and emits existing `ThemeScanObservation` objects.

**Tech Stack:** Python 3.11, dataclasses, Enum, PyYAML, pytest, Ruff; no provider SDK or network dependency.

**Spec:** `docs/superpowers/specs/2026-09-19-market-observation-adapter-design.md`

## Global Constraints

- Core code is provider-agnostic; no Alpaca/Yahoo/Polygon/Bloomberg imports.
- MarketBar is daily-close only in v0.1: `symbol`, `session_date`, `available_at`, `close`.
- Candidate effective windows remain half-open: `effective_from <= session_date < effective_to`.
- Current basket cohort must be effective for the entire current window.
- Novelty uses one stable cohort effective across prior start through current end.
- Membership/composition change must never masquerade as novelty.
- PROXY mode uses only explicitly declared proxies; no substitution/discovery.
- Missing coverage returns `COVERAGE_PENDING`; malformed or contradictory inputs raise `ValueError`.
- READY outputs use `source_type="derived_feature"`, `is_independent=True`, `observed_or_inferred="inferred"`.
- Raw diagnostics and normalized scanner signals are both retained.
- Version 0.1 normalization/support thresholds are labeled `uncalibrated`.
- No scanner-score changes, research-budget changes, ThemeKey changes, Tape/router changes, live ledger writes, scheduled jobs, or brokerage execution.
- Tests use synthetic/public-safe bars and never make network calls.

## Review Focus

1. **Unused malformed bars:** a bad duplicate/future/nonpositive bar for an unrelated symbol must not invalidate a valid adapter result; semantically unused symbols are ignored before validation.
2. **Date-only cycle boundary:** `cycle_as_of="2026-09-19"` means end-of-day UTC; a used bar available at 2026-09-19T16:00Z is allowed, while 2026-09-20T00:00Z is rejected.
3. **Effective-to half-open boundary:** a candidate with `effective_to="2026-09-18"` is not eligible on the 2026-09-18 session and must not leak into current/stable baskets.
4. **Composition-as-novelty:** a member admitted only in the current window may affect neither full-window current basket metrics nor stable-cohort novelty; current/stable cohort differences must be explicit.
5. **Semantic hashing:** reversing input row order or adding unrelated symbols must leave diagnostics, source-level input hashes, batch input hash, and emitted observations identical.

---

## File map

- Create `src/decision_lab/market_observation.py`
  - data classes/enums;
  - config/spec loaders and validation;
  - bar normalization;
  - benchmark session-window selection;
  - BASKET calculations;
  - PROXY calculations;
  - normalization/support direction;
  - source/batch provenance hashing;
  - adapter output.
- Create `config/adapters/market_observation_defaults.yaml`
  - exact uncalibrated v0.1 transform thresholds.
- Create `config/market_observations/datacenter_infra.yaml`
  - basket/SPY spec.
- Create `config/market_observations/genomics_bio.yaml`
  - proxy/SPY/ARKG/XBI spec.
- Create `tests/test_market_observation.py`
  - synthetic fixtures + all adapter behavior.
- Modify `src/decision_lab/__init__.py`
  - narrow public exports only.
- Do not modify `src/decision_lab/scanner.py`, `research_budget.py`, `themes.py`, `tape.py`, `playbooks.py`, `hierarchical.py`, or `ledger.py` unless a failing regression proves an unavoidable defect. If such a change becomes necessary, stop and upgrade scope before editing it.

---

### Task 1: Typed market bars, specs/config, validation, and benchmark windows

**Files:**
- Create: `src/decision_lab/market_observation.py`
- Create: `tests/test_market_observation.py`

**Interfaces:**
- Consumes:
  - `decision_lab.scanner.SupportDirection`
  - `decision_lab.scanner.ThemeScanObservation`
  - `decision_lab.themes.ThemePackage`
  - `decision_lab.ledger.canonical_hash(payload) -> str`
- Produces:
  - `MarketBar`
  - `MarketObservationMode`
  - `MarketObservationStatus`
  - `MarketObservationSpec`
  - `MarketObservationConfig`
  - `MarketObservationDiagnostics`
  - `MarketObservationBatch`
  - `adapt_market_observations(...)`
  - loaders are added in Task 4.

- [ ] **Step 1: Write RED tests for the input/session boundary**

Create `tests/test_market_observation.py` with:

```python
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
        _bar("SPY", "2026-09-16", 100),
        _bar("SPY", "2026-09-17", 101),
        _bar("SPY", "2026-09-18", 102),
        _bar("SPY", "2026-09-19", 103, available_at="2026-09-19T16:00:00+00:00"),
        _bar("SPY", "2026-09-15", 99),
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
    future[-2] = _bar(
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
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest -q tests/test_market_observation.py
```

Expected: collection failure because `decision_lab.market_observation` does not exist.

- [ ] **Step 3: Implement typed interfaces and benchmark-window validation**

Create `src/decision_lab/market_observation.py` with this public skeleton:

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import Enum
from math import isfinite
from pathlib import Path

import yaml

from .ledger import canonical_hash
from .scanner import SupportDirection, ThemeScanObservation
from .themes import ThemePackage


class MarketObservationMode(str, Enum):
    BASKET = "basket"
    PROXY = "proxy"


class MarketObservationStatus(str, Enum):
    READY = "ready"
    COVERAGE_PENDING = "coverage_pending"


@dataclass(frozen=True)
class MarketBar:
    symbol: str
    session_date: str
    available_at: str
    close: float

    def validate(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must be non-empty")
        try:
            date.fromisoformat(self.session_date)
        except ValueError as exc:
            raise ValueError("invalid session_date") from exc
        _parse_utc(self.available_at)
        if not isfinite(self.close) or self.close <= 0:
            raise ValueError("close must be finite and positive")


@dataclass(frozen=True)
class MarketObservationSpec:
    theme_id: str
    mode: MarketObservationMode
    benchmark: str
    proxies: tuple[str, ...] = ()
    current_return_sessions: int = 5
    prior_return_sessions: int = 5
    min_basket_members: int = 3
    version: str = "0.1"

    def validate(self) -> None:
        if not self.theme_id.strip():
            raise ValueError("theme_id must be non-empty")
        if not self.benchmark.strip():
            raise ValueError("benchmark must be non-empty")
        if self.current_return_sessions < 1 or self.prior_return_sessions < 1:
            raise ValueError("return sessions must be positive")
        if self.min_basket_members < 1:
            raise ValueError("min_basket_members must be positive")
        normalized = tuple(p.upper() for p in self.proxies)
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate proxies")
        if self.benchmark.upper() in normalized:
            raise ValueError("proxy cannot equal benchmark")
        if self.mode is MarketObservationMode.PROXY and not normalized:
            raise ValueError("proxy mode requires at least one proxy")


@dataclass(frozen=True)
class MarketObservationConfig:
    version: str = "0.1"
    calibration_label: str = "uncalibrated"
    relative_strength_scale: float = 0.20
    novelty_scale: float = 0.10
    basket_support_excess_min: float = 0.02
    basket_support_breadth_min: float = 0.60
    basket_contradiction_excess_max: float = -0.02
    basket_contradiction_breadth_max: float = 0.25
    proxy_support_excess_min: float = 0.02
    proxy_support_persistence_min: float = 0.60
    proxy_contradiction_excess_max: float = -0.02
    proxy_contradiction_persistence_max: float = 0.40

    def validate(self) -> None:
        if self.relative_strength_scale <= 0 or self.novelty_scale <= 0:
            raise ValueError("normalization scales must be positive")
        for value in (
            self.basket_support_breadth_min,
            self.basket_contradiction_breadth_max,
            self.proxy_support_persistence_min,
            self.proxy_contradiction_persistence_max,
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError("breadth/persistence thresholds must be in [0,1]")
        for value in (
            self.basket_support_excess_min,
            self.basket_contradiction_excess_max,
            self.proxy_support_excess_min,
            self.proxy_contradiction_excess_max,
        ):
            if not isfinite(value):
                raise ValueError("excess thresholds must be finite")
        if (
            self.basket_contradiction_excess_max >= self.basket_support_excess_min
            and self.basket_contradiction_breadth_max >= self.basket_support_breadth_min
        ):
            raise ValueError("basket support/contradiction regions overlap")
        if (
            self.proxy_contradiction_excess_max >= self.proxy_support_excess_min
            and self.proxy_contradiction_persistence_max
            >= self.proxy_support_persistence_min
        ):
            raise ValueError("proxy support/contradiction regions overlap")


@dataclass(frozen=True)
class MarketObservationDiagnostics:
    theme_id: str
    mode: MarketObservationMode
    instrument: str
    benchmark: str
    market_as_of: str | None
    current_start: str | None
    current_end: str | None
    prior_start: str | None
    prior_end: str | None
    status: MarketObservationStatus
    reason: str
    current_return: float | None = None
    benchmark_current_return: float | None = None
    current_excess_return: float | None = None
    comparison_current_excess_return: float | None = None
    comparison_prior_excess_return: float | None = None
    novelty_abs_excess_change: float | None = None
    breadth: float | None = None
    persistence: float | None = None
    current_member_symbols: tuple[str, ...] = ()
    stable_member_symbols: tuple[str, ...] = ()
    current_member_count: int = 0
    stable_member_count: int = 0
    membership_changed: bool = False
    support_direction: SupportDirection = SupportDirection.NEUTRAL
    relative_strength_signal: float | None = None
    breadth_signal: float | None = None
    persistence_signal: float | None = None
    novelty_signal: float | None = None
    universe_version: str = ""
    package_version: str = ""
    spec_version: str = ""
    config_version: str = ""
    input_hash: str = ""
    spec_hash: str = ""
    config_hash: str = ""
    diagnostic_hash: str | None = None
    evidence_refs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketObservationBatch:
    theme_id: str
    cycle_as_of: str
    market_as_of: str | None
    observations: tuple[ThemeScanObservation, ...]
    diagnostics: tuple[MarketObservationDiagnostics, ...]
    input_hash: str
    spec_hash: str
    config_hash: str
```

Private helpers in Task 1:

```python
def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _cycle_end(value: str) -> datetime:
    dt = _parse_utc(value)
    if "T" not in value and " " not in value:
        return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


def _required_symbols(package: ThemePackage, spec: MarketObservationSpec) -> set[str]:
    symbols = {spec.benchmark.upper()}
    if spec.mode is MarketObservationMode.PROXY:
        symbols.update(p.upper() for p in spec.proxies)
    else:
        symbols.update(package.universe.symbols())
    return symbols
```

Important validation order in `adapt_market_observations`:

1. validate spec/config/theme match;
2. determine required symbols;
3. discard rows whose uppercase symbol is not required;
4. validate only remaining rows;
5. normalize symbol uppercase;
6. reject duplicate `(symbol, session_date)`;
7. reject required rows with `available_at > _cycle_end(cycle_as_of)`;
8. build benchmark session dates;
9. if benchmark has fewer than `current_return_sessions + prior_return_sessions + 1` sessions, return one COVERAGE_PENDING diagnostic.

The Task-1 coverage diagnostic has all numeric fields None, exact package/universe/spec/config versions and hashes, and `input_hash` over the used benchmark bars.

- [ ] **Step 4: Run Task-1 tests and verify GREEN**

Run:

```bash
pytest -q tests/test_market_observation.py
pytest -q
```

Expected: new tests and all pre-existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/decision_lab/market_observation.py tests/test_market_observation.py
git commit -m "feat: add market observation input boundary"
```

---

### Task 2: BASKET mode, effective membership, stable-cohort novelty, and basket support direction

**Files:**
- Modify: `src/decision_lab/market_observation.py`
- Modify: `tests/test_market_observation.py`

**Interfaces:**
- Extends Task-1 `adapt_market_observations`; public signature does not change.

- [ ] **Step 1: Add RED BASKET fixtures and tests**

Append imports:

```python
from decision_lab.universe import Candidate
```

Add helpers:

```python
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
```

Use two-session current and two-session prior windows, requiring five benchmark sessions.

Add:

```python
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
```

- [ ] **Step 2: Run BASKET tests and verify RED**

Run:

```bash
pytest -q tests/test_market_observation.py
```

Expected: Task-1 tests stay green; BASKET metric/effective-date tests fail.

- [ ] **Step 3: Implement BASKET mode minimally**

Implement helpers:

```python
def _price_index(
    bars: Sequence[MarketBar],
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for bar in bars:
        out.setdefault(bar.symbol.upper(), {})[bar.session_date] = float(bar.close)
    return out


def _return(prices: dict[str, float], start: str, end: str) -> float:
    return prices[end] / prices[start] - 1.0


def _has_all_sessions(prices: dict[str, float], sessions: Sequence[str]) -> bool:
    return all(session in prices for session in sessions)


def _candidate_effective_for_window(candidate, start: str, end: str) -> bool:
    return candidate.is_effective(start) and candidate.is_effective(end)
```

Important BASKET algorithm:

- current sessions = benchmark session slice from current start through current end inclusive;
- prior sessions = benchmark session slice from prior start through prior end inclusive;
- current cohort:
  - effective at current_start and current_end;
  - has all current sessions;
- stable cohort:
  - effective at prior_start and current_end;
  - has all prior+current sessions;
- candidate with `effective_to == current_end` fails `candidate.is_effective(current_end)`;
- basket return = arithmetic mean of endpoint member returns;
- breadth = fraction member endpoint returns > 0;
- persistence = fraction current one-session basket returns > one-session benchmark returns;
- current excess uses current cohort;
- comparison prior/current excess both use stable cohort;
- novelty uses comparison excess difference only;
- current valid + stable too small => READY with `novelty_signal=None` and warning;
- current too small => COVERAGE_PENDING, no observation.

Support direction:

```python
if (
    current_excess >= config.basket_support_excess_min
    and breadth >= config.basket_support_breadth_min
):
    direction = SupportDirection.SUPPORTING
elif (
    current_excess <= config.basket_contradiction_excess_max
    and breadth <= config.basket_contradiction_breadth_max
):
    direction = SupportDirection.CONTRADICTING
else:
    direction = SupportDirection.NEUTRAL
```

Normalization:

```python
relative_strength_signal = _clip01(
    0.5 + current_excess / config.relative_strength_scale
)
breadth_signal = breadth
persistence_signal = persistence
novelty_signal = (
    None
    if novelty_abs_excess_change is None
    else _clip01(novelty_abs_excess_change / config.novelty_scale)
)
```

- [ ] **Step 4: Run BASKET tests + full suite**

Run:

```bash
pytest -q tests/test_market_observation.py
pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/decision_lab/market_observation.py tests/test_market_observation.py
git commit -m "feat: add effective-dated basket market observations"
```

---

### Task 3: PROXY mode, provenance hashes, deterministic output, and scanner compatibility

**Files:**
- Modify: `src/decision_lab/market_observation.py`
- Modify: `tests/test_market_observation.py`

**Interfaces:**
- Extends `adapt_market_observations`; public signature remains unchanged.
- Produces finalized `MarketObservationBatch` provenance and READY `ThemeScanObservation` records.

- [ ] **Step 1: Add RED PROXY and hashing tests**

Add:

```python
from decision_lab.scanner import ScannerConfig, rank_themes


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
```

Add `from decision_lab.ledger import canonical_hash`.

- [ ] **Step 2: Run PROXY tests and verify RED**

Run:

```bash
pytest -q tests/test_market_observation.py
```

Expected: PROXY/provenance assertions fail while Task-1/2 tests remain green.

- [ ] **Step 3: Implement PROXY calculations and deterministic provenance**

For a proxy READY source:

- require every benchmark session in the two adjacent windows;
- compute current/proior proxy and benchmark returns;
- `comparison_current_excess_return = current_excess_return`;
- `comparison_prior_excess_return = proxy_prior_return - benchmark_prior_return`;
- persistence = fraction current daily proxy returns > benchmark;
- breadth fields stay None;
- support direction follows proxy thresholds.

Hash helpers:

```python
def _used_bar_payload(
    bars: Sequence[MarketBar],
    symbols: set[str],
    session_dates: set[str],
) -> list[dict[str, object]]:
    rows = [
        {
            "symbol": bar.symbol.upper(),
            "session_date": bar.session_date,
            "available_at": _parse_utc(bar.available_at).isoformat(),
            "close": float(bar.close),
        }
        for bar in bars
        if bar.symbol.upper() in symbols and bar.session_date in session_dates
    ]
    return sorted(rows, key=lambda row: (row["symbol"], row["session_date"]))


def _with_diagnostic_hash(
    diagnostic: MarketObservationDiagnostics,
) -> MarketObservationDiagnostics:
    payload = asdict(diagnostic)
    payload["diagnostic_hash"] = None
    digest = canonical_hash(payload)
    return replace(diagnostic, diagnostic_hash=digest)
```

For each READY diagnostic:

```python
source_ref = (
    f"market_observation:{spec.theme_id}:{spec.mode.value}:"
    f"{instrument}:{market_as_of}:{diagnostic.input_hash[:12]}"
)
```

Observation evidence refs:

```python
(
    market_source_ref,
    f"diagnostic:{diagnostic.diagnostic_hash}",
    f"package:{spec.theme_id}@{package.version}",
    f"universe:{spec.theme_id}@{package.universe.version}",
    # plus f"proxy:{instrument}" for PROXY
)
```

Batch input hash:

```python
canonical_hash(sorted(d.input_hash for d in diagnostics))
```

Diagnostics and observations must sort by lexical instrument.

- [ ] **Step 4: Run adapter tests + full regression**

Run:

```bash
pytest -q tests/test_market_observation.py
pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/decision_lab/market_observation.py tests/test_market_observation.py
git commit -m "feat: add proxy observations and deterministic provenance"
```

---

### Task 4: Versioned YAML loaders, real-theme contracts, Genomics no-retro fixture, and public API

**Files:**
- Create: `config/adapters/market_observation_defaults.yaml`
- Create: `config/market_observations/datacenter_infra.yaml`
- Create: `config/market_observations/genomics_bio.yaml`
- Modify: `src/decision_lab/market_observation.py`
- Modify: `src/decision_lab/__init__.py`
- Modify: `tests/test_market_observation.py`

**Interfaces:**
- Produces:
  - `load_market_observation_config(path) -> MarketObservationConfig`
  - `load_market_observation_spec(path) -> MarketObservationSpec`
  - public package exports.

- [ ] **Step 1: Add RED loader/public/real-theme tests**

Append:

```python
from pathlib import Path

from decision_lab.market_observation import (
    load_market_observation_config,
    load_market_observation_spec,
)
from decision_lab.themes import load_theme_package

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
```

- [ ] **Step 2: Run loader/public tests and verify RED**

Run:

```bash
pytest -q tests/test_market_observation.py
```

Expected: YAML files/loaders/public exports missing.

- [ ] **Step 3: Add exact YAML files**

Create `config/adapters/market_observation_defaults.yaml`:

```yaml
version: "0.1"
calibration_label: uncalibrated
relative_strength_scale: 0.20
novelty_scale: 0.10
basket_support_excess_min: 0.02
basket_support_breadth_min: 0.60
basket_contradiction_excess_max: -0.02
basket_contradiction_breadth_max: 0.25
proxy_support_excess_min: 0.02
proxy_support_persistence_min: 0.60
proxy_contradiction_excess_max: -0.02
proxy_contradiction_persistence_max: 0.40
```

Create `config/market_observations/datacenter_infra.yaml`:

```yaml
version: "0.1"
theme_id: DataCenter_Infra
mode: basket
benchmark: SPY
proxies: []
current_return_sessions: 5
prior_return_sessions: 5
min_basket_members: 3
```

Create `config/market_observations/genomics_bio.yaml`:

```yaml
version: "0.1"
theme_id: Genomics_Bio
mode: proxy
benchmark: SPY
proxies: [ARKG, XBI]
current_return_sessions: 5
prior_return_sessions: 5
min_basket_members: 3
```

- [ ] **Step 4: Add loaders**

```python
def load_market_observation_config(path: str | Path) -> MarketObservationConfig:
    payload = dict(yaml.safe_load(Path(path).read_text()) or {})
    payload["calibration_label"] = "uncalibrated"
    config = MarketObservationConfig(**payload)
    config.validate()
    return config


def load_market_observation_spec(path: str | Path) -> MarketObservationSpec:
    payload = dict(yaml.safe_load(Path(path).read_text()) or {})
    payload["mode"] = MarketObservationMode(payload["mode"])
    payload["proxies"] = tuple(str(x).upper() for x in payload.get("proxies", ()))
    payload["benchmark"] = str(payload["benchmark"]).upper()
    spec = MarketObservationSpec(**payload)
    spec.validate()
    return spec
```

- [ ] **Step 5: Export public interfaces**

Modify `src/decision_lab/__init__.py` to import/export exactly:

```python
from .market_observation import (
    MarketBar,
    MarketObservationBatch,
    MarketObservationConfig,
    MarketObservationDiagnostics,
    MarketObservationMode,
    MarketObservationSpec,
    MarketObservationStatus,
    adapt_market_observations,
    load_market_observation_config,
    load_market_observation_spec,
)
```

Add all ten names to sorted `__all__`.

- [ ] **Step 6: Run adapter + full suite**

Run:

```bash
pytest -q tests/test_market_observation.py
pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add config/adapters/market_observation_defaults.yaml config/market_observations/datacenter_infra.yaml config/market_observations/genomics_bio.yaml src/decision_lab/market_observation.py src/decision_lab/__init__.py tests/test_market_observation.py
git commit -m "config: publish market observation adapter contracts"
```

---

### Task 5: Whole-branch safety audit and final verification

**Files:**
- Verify: `src/decision_lab/market_observation.py`
- Verify: `src/decision_lab/__init__.py`
- Verify: `tests/test_market_observation.py`
- Verify: three new YAML files
- Review-only: scanner/budget/ThemeKey/Tape/router/linkage/ledger modules

**Interfaces:**
- Produces verification evidence only; no new behavior.

- [ ] **Step 1: Run fresh full regression**

Run:

```bash
pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run changed-files Ruff**

Run:

```bash
python -m ruff check   src/decision_lab/market_observation.py   src/decision_lab/__init__.py   tests/test_market_observation.py
```

Expected: exit 0.

- [ ] **Step 3: Audit forbidden semantic drift**

Verify no diffs to:

```text
src/decision_lab/scanner.py
src/decision_lab/research_budget.py
src/decision_lab/themes.py
src/decision_lab/tape.py
src/decision_lab/playbooks.py
src/decision_lab/hierarchical.py
src/decision_lab/ledger.py
.github/workflows/
```

Also verify no provider SDK import:

```bash
grep -R -E "alpaca|polygon|yfinance|bloomberg" src/decision_lab/market_observation.py
```

Expected: no matches.

- [ ] **Step 4: Whole-branch review against Review Focus**

Check specifically:

- malformed unused symbols are ignored before validation;
- used duplicate/future bars fail closed;
- date-only cycle timing is end-of-day UTC;
- effective_to is half-open;
- current cohort and stable cohort are distinct;
- novelty never uses changing composition;
- one missing proxy does not suppress valid peers;
- source/batch hashes use only semantically used bars;
- diagnostic hash binds all diagnostics;
- emitted observations satisfy scanner source metadata constraints;
- no direct permission or execution path exists.

Any Critical/Important issue gets one TDD fix pass: write a reproducing RED test, make it GREEN, then rerun full suite and Ruff.

- [ ] **Step 5: Exact-final-tree verification**

On the exact final head:

```bash
pytest -q
python -m ruff check   src/decision_lab/market_observation.py   src/decision_lab/__init__.py   tests/test_market_observation.py
```

Record exact pytest count/time and Ruff result.

- [ ] **Step 6: Keep branch unmerged**

Do not merge during implementation. Present integration options after final verification and whole-branch review are green.
