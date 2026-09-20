from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import Enum

from .ledger import canonical_hash
from .market_observation import (
    MarketBar,
    MarketObservationBatch,
    MarketObservationConfig,
    MarketObservationSpec,
    adapt_market_observations,
)
from .research_budget import (
    ResearchAllocation,
    ResearchBudgetAllocator,
    ResearchBudgetConfig,
)
from .scanner import (
    ScannerConfig,
    ThemeScanObservation,
    ThemeScanResult,
    rank_themes,
)
from .themes import ThemeDefinition, ThemePackage


class ReplayStatus(str, Enum):
    ROUTED = "routed"
    NO_OBSERVATION = "no_observation"


@dataclass(frozen=True)
class ThemeReplayInput:
    package: ThemePackage
    market_spec: MarketObservationSpec
    market_config: MarketObservationConfig
    bars: tuple[MarketBar, ...]
    market_source_ref: str


@dataclass(frozen=True)
class ReplayCycleInput:
    cycle_as_of: str
    themes: tuple[ThemeReplayInput, ...] = ()
    external_observations: tuple[ThemeScanObservation, ...] = ()
    prior_scan_results: tuple[ThemeScanResult, ...] = ()
    prior_allocations: tuple[ResearchAllocation, ...] = ()
    scanner_config: ScannerConfig = field(default_factory=ScannerConfig)
    budget_config: ResearchBudgetConfig = field(default_factory=ResearchBudgetConfig)


@dataclass(frozen=True)
class ReplayThemeRecord:
    theme_id: str
    registered: bool
    market_batch: MarketObservationBatch | None
    scan_result: ThemeScanResult | None
    allocation: ResearchAllocation | None
    replay_status: ReplayStatus


@dataclass(frozen=True)
class ReplayCycleResult:
    cycle_as_of: str
    market_batches: tuple[MarketObservationBatch, ...]
    combined_observations: tuple[ThemeScanObservation, ...]
    scan_results: tuple[ThemeScanResult, ...]
    allocations: tuple[ResearchAllocation, ...]
    theme_records: tuple[ReplayThemeRecord, ...]
    input_hash: str
    result_hash: str


def _parse_cycle_date(value: str) -> date:
    if "T" not in value and " " not in value:
        return date.fromisoformat(value)
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).date()


def _definition_is_effective(
    definition: ThemeDefinition,
    cycle_date: date,
) -> bool:
    try:
        effective_from = (
            None
            if definition.effective_from is None
            else date.fromisoformat(definition.effective_from)
        )
        effective_to = (
            None
            if definition.effective_to is None
            else date.fromisoformat(definition.effective_to)
        )
    except ValueError as exc:
        raise ValueError("invalid theme package effective date") from exc

    if effective_from is not None and cycle_date < effective_from:
        return False
    return effective_to is None or cycle_date < effective_to


def _definition_semantic_payload(
    definition: ThemeDefinition,
) -> dict[str, object]:
    return {
        "theme_id": definition.theme_id,
        "lifecycle_state": definition.lifecycle_state.value,
        "effective_from": definition.effective_from,
        "effective_to": definition.effective_to,
        "version": definition.version,
        "provenance": list(definition.provenance),
    }


def _definition_semantic_hash(definition: ThemeDefinition) -> str:
    return canonical_hash(_definition_semantic_payload(definition))


def _universe_semantic_payload(universe) -> dict[str, object]:
    candidates = []
    for candidate in sorted(
        universe.candidates.values(),
        key=lambda item: item.ticker.upper(),
    ):
        candidates.append(
            {
                "ticker": candidate.ticker.upper(),
                "theme": candidate.theme,
                "layer": candidate.layer,
                "membership_state": candidate.membership_state,
                "effective_from": candidate.effective_from,
                "effective_to": candidate.effective_to,
                "provenance": list(candidate.provenance),
            }
        )
    return {
        "theme": universe.theme,
        "version": universe.version,
        "layers": sorted(universe.layers),
        "candidates": candidates,
    }


def _universe_semantic_hash(universe) -> str:
    return canonical_hash(_universe_semantic_payload(universe))


def _observation_sort_key(
    item: ThemeScanObservation,
) -> tuple[str, str, str, str]:
    return (
        item.theme_id,
        item.as_of,
        item.source_ref,
        canonical_hash(asdict(item)),
    )


def _scan_sort_key(item: ThemeScanResult) -> tuple[str, str, str]:
    return (
        item.theme_id,
        item.as_of,
        canonical_hash(asdict(item)),
    )


def _allocation_sort_key(item: ResearchAllocation) -> tuple[str, str, str]:
    return (
        item.theme_id,
        item.as_of,
        canonical_hash(asdict(item)),
    )


def _theme_replay_semantic_payload(
    theme_input: ThemeReplayInput,
    batch: MarketObservationBatch,
) -> dict[str, object]:
    package = theme_input.package
    return {
        "theme_id": package.definition.theme_id,
        "definition_semantic_hash": _definition_semantic_hash(
            package.definition
        ),
        "package_version": package.version,
        "universe_version": package.universe.version,
        "universe_semantic_hash": _universe_semantic_hash(
            package.universe
        ),
        "market_spec_hash": batch.spec_hash,
        "market_config_hash": batch.config_hash,
        "market_input_hash": batch.input_hash,
        "market_source_ref": theme_input.market_source_ref,
    }


def _validate_replay_input(
    replay_input: ReplayCycleInput,
) -> tuple[date, tuple[ThemeReplayInput, ...]]:
    cycle_date = _parse_cycle_date(replay_input.cycle_as_of)
    sorted_themes = tuple(
        sorted(
            replay_input.themes,
            key=lambda item: item.package.definition.theme_id,
        )
    )
    seen: set[str] = set()
    for theme_input in sorted_themes:
        theme_id = theme_input.package.definition.theme_id
        if not theme_id.strip():
            raise ValueError("theme package theme_id must be non-empty")
        if theme_id in seen:
            raise ValueError("duplicate replay theme")
        seen.add(theme_id)
        if not theme_input.market_source_ref.strip():
            raise ValueError("market_source_ref must be non-empty")
        if not _definition_is_effective(
            theme_input.package.definition,
            cycle_date,
        ):
            raise ValueError("theme package not effective at cycle_as_of")
    return cycle_date, sorted_themes


def _empty_hash_payload(
    replay_input: ReplayCycleInput,
    sorted_prior_scans: tuple[ThemeScanResult, ...],
    sorted_prior_allocations: tuple[ResearchAllocation, ...],
) -> dict[str, object]:
    return {
        "cycle_as_of": replay_input.cycle_as_of,
        "registered_themes": [],
        "external_observations": [],
        "prior_scan_results": [asdict(item) for item in sorted_prior_scans],
        "prior_allocations": [
            asdict(item) for item in sorted_prior_allocations
        ],
        "scanner_config": asdict(replay_input.scanner_config),
        "budget_config": asdict(replay_input.budget_config),
    }


def run_replay_cycle(
    replay_input: ReplayCycleInput,
) -> ReplayCycleResult:
    _cycle_date, sorted_themes = _validate_replay_input(replay_input)

    sorted_prior_scans = tuple(
        sorted(replay_input.prior_scan_results, key=_scan_sort_key)
    )
    sorted_prior_allocations = tuple(
        sorted(replay_input.prior_allocations, key=_allocation_sort_key)
    )
    sorted_external = tuple(
        sorted(replay_input.external_observations, key=_observation_sort_key)
    )

    market_batches = tuple(
        adapt_market_observations(
            package=theme_input.package,
            bars=theme_input.bars,
            spec=theme_input.market_spec,
            config=theme_input.market_config,
            cycle_as_of=replay_input.cycle_as_of,
            market_source_ref=theme_input.market_source_ref,
        )
        for theme_input in sorted_themes
    )

    market_observations = tuple(
        observation
        for batch in market_batches
        for observation in batch.observations
    )
    combined_observations = tuple(
        sorted(
            (*market_observations, *sorted_external),
            key=_observation_sort_key,
        )
    )

    registry_state = {
        theme_input.package.definition.theme_id: theme_input.package.definition
        for theme_input in sorted_themes
    }

    scan_results = tuple(
        sorted(
            rank_themes(
                combined_observations,
                registry_state,
                sorted_prior_scans,
                replay_input.scanner_config,
                cycle_as_of=replay_input.cycle_as_of,
            ),
            key=lambda item: item.theme_id,
        )
    )
    allocations = tuple(
        sorted(
            ResearchBudgetAllocator().allocate(
                scan_results,
                registry_state,
                sorted_prior_allocations,
                replay_input.budget_config,
                cycle_as_of=replay_input.cycle_as_of,
            ),
            key=lambda item: item.theme_id,
        )
    )

    batch_by_theme = {batch.theme_id: batch for batch in market_batches}
    scan_by_theme = {item.theme_id: item for item in scan_results}
    allocation_by_theme = {item.theme_id: item for item in allocations}
    registered_theme_ids = set(registry_state)
    current_theme_ids = sorted(
        registered_theme_ids
        | {observation.theme_id for observation in sorted_external}
    )

    theme_records: list[ReplayThemeRecord] = []
    for theme_id in current_theme_ids:
        scan = scan_by_theme.get(theme_id)
        allocation = allocation_by_theme.get(theme_id)
        if scan is None:
            if allocation is not None:
                raise RuntimeError("allocation exists without scan result")
            replay_status = ReplayStatus.NO_OBSERVATION
        else:
            if allocation is None:
                raise RuntimeError("scan result exists without allocation")
            replay_status = ReplayStatus.ROUTED

        theme_records.append(
            ReplayThemeRecord(
                theme_id=theme_id,
                registered=theme_id in registered_theme_ids,
                market_batch=batch_by_theme.get(theme_id),
                scan_result=scan,
                allocation=allocation,
                replay_status=replay_status,
            )
        )

    theme_records_tuple = tuple(theme_records)

    input_payload = {
        "cycle_as_of": replay_input.cycle_as_of,
        "registered_themes": [
            _theme_replay_semantic_payload(
                theme_input,
                batch_by_theme[theme_input.package.definition.theme_id],
            )
            for theme_input in sorted_themes
        ],
        "external_observations": [
            asdict(item) for item in sorted_external
        ],
        "prior_scan_results": [
            asdict(item) for item in sorted_prior_scans
        ],
        "prior_allocations": [
            asdict(item) for item in sorted_prior_allocations
        ],
        "scanner_config": asdict(replay_input.scanner_config),
        "budget_config": asdict(replay_input.budget_config),
    }
    input_hash = canonical_hash(input_payload)
    result_payload = {
        "cycle_as_of": replay_input.cycle_as_of,
        "input_hash": input_hash,
        "market_batches": [asdict(item) for item in market_batches],
        "combined_observations": [
            asdict(item) for item in combined_observations
        ],
        "scan_results": [asdict(item) for item in scan_results],
        "allocations": [asdict(item) for item in allocations],
        "theme_records": [asdict(item) for item in theme_records_tuple],
    }
    result_hash = canonical_hash(result_payload)

    return ReplayCycleResult(
        cycle_as_of=replay_input.cycle_as_of,
        market_batches=market_batches,
        combined_observations=combined_observations,
        scan_results=scan_results,
        allocations=allocations,
        theme_records=theme_records_tuple,
        input_hash=input_hash,
        result_hash=result_hash,
    )
