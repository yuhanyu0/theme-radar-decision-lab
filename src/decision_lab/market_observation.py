from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from enum import Enum
from math import isfinite

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
        try:
            _parse_utc(self.available_at)
        except ValueError as exc:
            raise ValueError("invalid available_at") from exc
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
        normalized = tuple(proxy.upper() for proxy in self.proxies)
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


def _symbol_rows(
    bars: Sequence[MarketBar],
    symbol: str,
) -> list[MarketBar]:
    target = symbol.upper()
    return [bar for bar in bars if bar.symbol.upper() == target]


def _validate_used_rows(
    rows: Sequence[MarketBar],
    *,
    cycle_end: datetime,
) -> list[MarketBar]:
    normalized: list[MarketBar] = []
    seen: set[tuple[str, str]] = set()
    for bar in rows:
        bar.validate()
        symbol = bar.symbol.upper()
        key = (symbol, bar.session_date)
        if key in seen:
            raise ValueError("duplicate symbol/session_date")
        seen.add(key)
        if _parse_utc(bar.available_at) > cycle_end:
            raise ValueError("required bar available after cycle_as_of")
        normalized.append(
            MarketBar(
                symbol=symbol,
                session_date=bar.session_date,
                available_at=_parse_utc(bar.available_at).isoformat(),
                close=float(bar.close),
            )
        )
    return sorted(normalized, key=lambda row: (row.symbol, row.session_date))


def _used_bar_payload(rows: Sequence[MarketBar]) -> list[dict[str, object]]:
    return [
        {
            "symbol": row.symbol,
            "session_date": row.session_date,
            "available_at": row.available_at,
            "close": row.close,
        }
        for row in rows
    ]


def _price_index(
    rows: Sequence[MarketBar],
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        out.setdefault(row.symbol.upper(), {})[row.session_date] = row.close
    return out


def _return(prices: dict[str, float], start: str, end: str) -> float:
    return prices[end] / prices[start] - 1.0


def _has_all_sessions(
    prices: dict[str, float],
    sessions: Sequence[str],
) -> bool:
    return all(session in prices for session in sessions)


def _candidate_effective_for_window(candidate, start: str, end: str) -> bool:
    return candidate.is_effective(start) and candidate.is_effective(end)


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _basket_direction(
    *,
    current_excess: float,
    breadth: float,
    config: MarketObservationConfig,
) -> SupportDirection:
    if (
        current_excess >= config.basket_support_excess_min
        and breadth >= config.basket_support_breadth_min
    ):
        return SupportDirection.SUPPORTING
    if (
        current_excess <= config.basket_contradiction_excess_max
        and breadth <= config.basket_contradiction_breadth_max
    ):
        return SupportDirection.CONTRADICTING
    return SupportDirection.NEUTRAL


def _member_rows_for_sessions(
    bars: Sequence[MarketBar],
    symbol: str,
    sessions: Sequence[str],
    *,
    cycle_end: datetime,
) -> list[MarketBar]:
    wanted = set(sessions)
    rows = [
        row
        for row in bars
        if row.symbol.upper() == symbol.upper() and row.session_date in wanted
    ]
    return _validate_used_rows(rows, cycle_end=cycle_end)


def _coverage_diagnostic(
    *,
    package: ThemePackage,
    spec: MarketObservationSpec,
    config: MarketObservationConfig,
    benchmark_rows: Sequence[MarketBar],
    market_as_of: str | None,
    current_start: str | None,
    current_end: str | None,
    prior_start: str | None,
    prior_end: str | None,
    reason: str,
    market_source_ref: str,
) -> MarketObservationDiagnostics:
    spec_hash = canonical_hash(asdict(spec))
    config_hash = canonical_hash(asdict(config))
    input_hash = canonical_hash(_used_bar_payload(benchmark_rows))
    return MarketObservationDiagnostics(
        theme_id=spec.theme_id,
        mode=spec.mode,
        instrument=spec.benchmark.upper(),
        benchmark=spec.benchmark.upper(),
        market_as_of=market_as_of,
        current_start=current_start,
        current_end=current_end,
        prior_start=prior_start,
        prior_end=prior_end,
        status=MarketObservationStatus.COVERAGE_PENDING,
        reason=reason,
        universe_version=package.universe.version,
        package_version=package.version,
        spec_version=spec.version,
        config_version=config.version,
        input_hash=input_hash,
        spec_hash=spec_hash,
        config_hash=config_hash,
        evidence_refs=(market_source_ref,),
    )


def adapt_market_observations(
    *,
    package: ThemePackage,
    bars: Sequence[MarketBar],
    spec: MarketObservationSpec,
    config: MarketObservationConfig,
    cycle_as_of: str,
    market_source_ref: str,
) -> MarketObservationBatch:
    spec.validate()
    config.validate()
    if spec.theme_id != package.definition.theme_id:
        raise ValueError("spec theme does not match package")

    cycle_end = _cycle_end(cycle_as_of)
    benchmark = spec.benchmark.upper()
    benchmark_rows = _validate_used_rows(
        _symbol_rows(bars, benchmark),
        cycle_end=cycle_end,
    )
    cycle_date = cycle_end.date()
    benchmark_rows = [
        row
        for row in benchmark_rows
        if date.fromisoformat(row.session_date) <= cycle_date
    ]

    spec_hash = canonical_hash(asdict(spec))
    config_hash = canonical_hash(asdict(config))
    required_sessions = (
        spec.current_return_sessions + spec.prior_return_sessions + 1
    )
    if len(benchmark_rows) < required_sessions:
        market_as_of = (
            benchmark_rows[-1].session_date if benchmark_rows else None
        )
        diagnostic = _coverage_diagnostic(
            package=package,
            spec=spec,
            config=config,
            benchmark_rows=benchmark_rows,
            market_as_of=market_as_of,
            current_start=None,
            current_end=market_as_of,
            prior_start=None,
            prior_end=None,
            reason="insufficient benchmark history",
            market_source_ref=market_source_ref,
        )
        return MarketObservationBatch(
            theme_id=spec.theme_id,
            cycle_as_of=cycle_as_of,
            market_as_of=market_as_of,
            observations=(),
            diagnostics=(diagnostic,),
            input_hash=canonical_hash([diagnostic.input_hash]),
            spec_hash=spec_hash,
            config_hash=config_hash,
        )

    sessions = [row.session_date for row in benchmark_rows]
    market_as_of = sessions[-1]
    current_end_index = len(sessions) - 1
    current_start_index = current_end_index - spec.current_return_sessions
    prior_end_index = current_start_index
    prior_start_index = prior_end_index - spec.prior_return_sessions
    current_start = sessions[current_start_index]
    prior_end = sessions[prior_end_index]
    prior_start = sessions[prior_start_index]

    if spec.mode is MarketObservationMode.PROXY:
        diagnostic = _coverage_diagnostic(
            package=package,
            spec=spec,
            config=config,
            benchmark_rows=benchmark_rows,
            market_as_of=market_as_of,
            current_start=current_start,
            current_end=market_as_of,
            prior_start=prior_start,
            prior_end=prior_end,
            reason="proxy observations not implemented",
            market_source_ref=market_source_ref,
        )
        return MarketObservationBatch(
            theme_id=spec.theme_id,
            cycle_as_of=cycle_as_of,
            market_as_of=market_as_of,
            observations=(),
            diagnostics=(diagnostic,),
            input_hash=canonical_hash([diagnostic.input_hash]),
            spec_hash=spec_hash,
            config_hash=config_hash,
        )

    current_sessions = sessions[current_start_index : current_end_index + 1]
    prior_sessions = sessions[prior_start_index : prior_end_index + 1]
    all_window_sessions = sessions[prior_start_index : current_end_index + 1]
    benchmark_prices = _price_index(benchmark_rows)[benchmark]
    benchmark_current_return = _return(
        benchmark_prices,
        current_start,
        market_as_of,
    )
    benchmark_prior_return = _return(
        benchmark_prices,
        prior_start,
        prior_end,
    )

    current_members: list[str] = []
    stable_members: list[str] = []
    prices_by_symbol: dict[str, dict[str, float]] = {}
    used_member_rows: list[MarketBar] = []

    for candidate in sorted(
        package.universe.candidates.values(),
        key=lambda item: item.ticker.upper(),
    ):
        symbol = candidate.ticker.upper()
        if not _candidate_effective_for_window(
            candidate,
            current_start,
            market_as_of,
        ):
            continue

        stable_effective = _candidate_effective_for_window(
            candidate,
            prior_start,
            market_as_of,
        )
        requested_sessions = (
            all_window_sessions if stable_effective else current_sessions
        )
        member_rows = _member_rows_for_sessions(
            bars,
            symbol,
            requested_sessions,
            cycle_end=cycle_end,
        )
        member_prices = _price_index(member_rows).get(symbol, {})
        if not _has_all_sessions(member_prices, current_sessions):
            continue

        current_members.append(symbol)
        prices_by_symbol[symbol] = member_prices
        if stable_effective and _has_all_sessions(
            member_prices,
            all_window_sessions,
        ):
            stable_members.append(symbol)
            used_member_rows.extend(member_rows)
        else:
            used_member_rows.extend(
                row
                for row in member_rows
                if row.session_date in set(current_sessions)
            )

    current_member_symbols = tuple(current_members)
    stable_member_symbols = tuple(stable_members)
    if len(current_members) < spec.min_basket_members:
        diagnostic = _coverage_diagnostic(
            package=package,
            spec=spec,
            config=config,
            benchmark_rows=benchmark_rows,
            market_as_of=market_as_of,
            current_start=current_start,
            current_end=market_as_of,
            prior_start=prior_start,
            prior_end=prior_end,
            reason="too few current basket members",
            market_source_ref=market_source_ref,
        )
        diagnostic = replace(
            diagnostic,
            instrument=spec.theme_id,
            current_member_symbols=current_member_symbols,
            stable_member_symbols=stable_member_symbols,
            current_member_count=len(current_members),
            stable_member_count=len(stable_members),
            membership_changed=current_member_symbols != stable_member_symbols,
        )
        return MarketObservationBatch(
            theme_id=spec.theme_id,
            cycle_as_of=cycle_as_of,
            market_as_of=market_as_of,
            observations=(),
            diagnostics=(diagnostic,),
            input_hash=canonical_hash([diagnostic.input_hash]),
            spec_hash=spec_hash,
            config_hash=config_hash,
        )

    member_returns = [
        _return(prices_by_symbol[symbol], current_start, market_as_of)
        for symbol in current_members
    ]
    current_return = sum(member_returns) / len(member_returns)
    breadth = sum(value > 0.0 for value in member_returns) / len(member_returns)

    outperforming = 0
    intervals = 0
    for start, end in zip(
        current_sessions,
        current_sessions[1:],
        strict=True,
    ):
        basket_daily = sum(
            _return(prices_by_symbol[symbol], start, end)
            for symbol in current_members
        ) / len(current_members)
        benchmark_daily = _return(benchmark_prices, start, end)
        outperforming += basket_daily > benchmark_daily
        intervals += 1
    persistence = outperforming / intervals

    current_excess = current_return - benchmark_current_return
    comparison_current_excess: float | None = None
    comparison_prior_excess: float | None = None
    novelty_abs_excess_change: float | None = None
    novelty_signal: float | None = None
    warnings: list[str] = []

    if len(stable_members) >= spec.min_basket_members:
        stable_current_return = sum(
            _return(prices_by_symbol[symbol], current_start, market_as_of)
            for symbol in stable_members
        ) / len(stable_members)
        stable_prior_return = sum(
            _return(prices_by_symbol[symbol], prior_start, prior_end)
            for symbol in stable_members
        ) / len(stable_members)
        comparison_current_excess = (
            stable_current_return - benchmark_current_return
        )
        comparison_prior_excess = stable_prior_return - benchmark_prior_return
        novelty_abs_excess_change = abs(
            comparison_current_excess - comparison_prior_excess
        )
        novelty_signal = _clip01(
            novelty_abs_excess_change / config.novelty_scale
        )
    else:
        warnings.append("insufficient stable comparison cohort")

    direction = _basket_direction(
        current_excess=current_excess,
        breadth=breadth,
        config=config,
    )
    relevant_benchmark_rows = [
        row
        for row in benchmark_rows
        if row.session_date in set(all_window_sessions)
    ]
    used_rows = sorted(
        relevant_benchmark_rows + used_member_rows,
        key=lambda row: (row.symbol, row.session_date),
    )
    input_hash = canonical_hash(_used_bar_payload(used_rows))
    relative_strength_signal = _clip01(
        0.5 + current_excess / config.relative_strength_scale
    )
    diagnostic = MarketObservationDiagnostics(
        theme_id=spec.theme_id,
        mode=spec.mode,
        instrument=spec.theme_id,
        benchmark=benchmark,
        market_as_of=market_as_of,
        current_start=current_start,
        current_end=market_as_of,
        prior_start=prior_start,
        prior_end=prior_end,
        status=MarketObservationStatus.READY,
        reason="ready",
        current_return=current_return,
        benchmark_current_return=benchmark_current_return,
        current_excess_return=current_excess,
        comparison_current_excess_return=comparison_current_excess,
        comparison_prior_excess_return=comparison_prior_excess,
        novelty_abs_excess_change=novelty_abs_excess_change,
        breadth=breadth,
        persistence=persistence,
        current_member_symbols=current_member_symbols,
        stable_member_symbols=stable_member_symbols,
        current_member_count=len(current_members),
        stable_member_count=len(stable_members),
        membership_changed=current_member_symbols != stable_member_symbols,
        support_direction=direction,
        relative_strength_signal=relative_strength_signal,
        breadth_signal=breadth,
        persistence_signal=persistence,
        novelty_signal=novelty_signal,
        universe_version=package.universe.version,
        package_version=package.version,
        spec_version=spec.version,
        config_version=config.version,
        input_hash=input_hash,
        spec_hash=spec_hash,
        config_hash=config_hash,
        evidence_refs=(market_source_ref,),
        warnings=tuple(warnings),
    )
    source_ref = (
        f"market_observation:{spec.theme_id}:{spec.mode.value}:"
        f"{spec.theme_id}:{market_as_of}:{input_hash[:12]}"
    )
    observation = ThemeScanObservation(
        theme_id=spec.theme_id,
        as_of=market_as_of,
        source_type="derived_feature",
        source_ref=source_ref,
        discovery_signal=None,
        structure_signal=None,
        persistence_signal=persistence,
        breadth_signal=breadth,
        relative_strength_signal=relative_strength_signal,
        volatility_signal=None,
        novelty_signal=novelty_signal,
        support_direction=direction,
        evidence_refs=(
            market_source_ref,
            f"package:{spec.theme_id}@{package.version}",
            f"universe:{spec.theme_id}@{package.universe.version}",
        ),
        is_independent=True,
        observed_or_inferred="inferred",
    )
    return MarketObservationBatch(
        theme_id=spec.theme_id,
        cycle_as_of=cycle_as_of,
        market_as_of=market_as_of,
        observations=(observation,),
        diagnostics=(diagnostic,),
        input_hash=canonical_hash([input_hash]),
        spec_hash=spec_hash,
        config_hash=config_hash,
    )
