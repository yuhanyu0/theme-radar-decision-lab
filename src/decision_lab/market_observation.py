from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
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

    reason = (
        "too few current basket members"
        if spec.mode is MarketObservationMode.BASKET
        else "proxy observations not implemented"
    )
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
        reason=reason,
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
