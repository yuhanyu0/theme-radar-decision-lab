# End-to-End Replay Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build a pure deterministic replay orchestrator that composes MarketObservationAdapter, World Scanner, and ResearchBudgetAllocator into one auditable research-allocation cycle.

**Architecture:** Add one focused replay.py module. It validates replay/package timing, canonicalizes current inputs, calls existing adapter/scanner/budget components without changing their semantics, constructs theme-level routing records, and computes semantic input/result hashes. The module has no filesystem or network side effects.

**Tech Stack:** Python 3.11, dataclasses, Enum, existing decision_lab components, pytest, Ruff.

**Spec:** docs/superpowers/specs/2026-09-19-end-to-end-replay-cycle-design.md

## Global Constraints

- Orchestration ends at ResearchAllocation; no company research, linkage, Tape, A-H routing, Decision Ledger, outcome evaluation, or execution.
- No filesystem reads/writes inside run_replay_cycle.
- No network calls, environment inspection, time.now, random IDs, scheduler, or provider SDK.
- Unknown themes may enter only through external ThemeScanObservation objects; replay never invents ThemeDefinition.
- Registered ThemePackage definitions must be effective at cycle_as_of.
- NO_OBSERVATION is not SCAN_ONLY.
- Market COVERAGE_PENDING is not an exception.
- Existing MarketObservationAdapter, Scanner, ResearchBudgetAllocator, ThemeKey, Tape, router, universe, and ledger behavior must not change.
- Replay hashing binds only semantic inputs; package.source_path, universe.generated_at, display/annotation fields excluded by the spec must not affect input_hash.
- Input tuple order must not affect input_hash, result_hash, or semantic output.
- Branch stays unmerged until exact-final-tree pytest, changed-files Ruff, and whole-branch review are green.

## Review Focus

1. **Prior-only ghosts:** prior scan/allocation history must never create a current ReplayThemeRecord when there is no registered theme or current external observation.
2. **Timestamp/date package validity:** date-only and offset-aware cycle_as_of values must resolve to the correct UTC cycle date; a future package must fail closed.
3. **NO_OBSERVATION versus SCAN_ONLY:** registered coverage-pending/no-external themes must have no scan/allocation, while unknown model-only themes must receive a real SCAN_ONLY allocation.
4. **Semantic-hash boundaries:** generated_at/source_path/annotation-only changes must not move input_hash, while used bars/effective dates/provenance/lifecycle/config/history changes must.
5. **Pure replay:** calling run_replay_cycle must leave ThemePackage/ThemeUniverse/config/history inputs unchanged and must not create files or depend on ambient clock/network state.

---

## File map

- Create src/decision_lab/replay.py
  - replay dataclasses/enums;
  - cycle/package validation;
  - canonical ordering;
  - definition/universe semantic payloads;
  - orchestration;
  - input/result hashing.
- Create tests/test_replay.py
  - typed validation;
  - status semantics;
  - determinism/hash tests;
  - real-package end-to-end fixtures.
- Modify src/decision_lab/__init__.py
  - narrow public exports only.
- Do not modify src/decision_lab/market_observation.py.
- Do not modify src/decision_lab/scanner.py.
- Do not modify src/decision_lab/research_budget.py.
- Do not modify src/decision_lab/themes.py.
- Do not modify src/decision_lab/universe.py.
- Do not modify src/decision_lab/tape.py, playbooks.py, hierarchical.py, ledger.py, or .github/workflows except a temporary branch-only lint workflow used for verification and removed before handoff.

---

### Task 1: Replay types, validation, semantic helpers, and empty-cycle determinism

**Files:**
- Create src/decision_lab/replay.py
- Create tests/test_replay.py

**Interfaces:**
- Consumes ThemePackage, MarketBar, MarketObservationSpec, MarketObservationConfig, ThemeScanObservation, ThemeScanResult, ResearchAllocation, ScannerConfig, ResearchBudgetConfig.
- Produces ThemeReplayInput, ReplayCycleInput, ReplayStatus, ReplayThemeRecord, ReplayCycleResult, run_replay_cycle.
- Private helpers established here are reused by later tasks:
  - _parse_cycle_date(value: str) -> date
  - _definition_semantic_payload(definition) -> dict[str, object]
  - _universe_semantic_payload(universe) -> dict[str, object]
  - _definition_semantic_hash(definition) -> str
  - _universe_semantic_hash(universe) -> str
  - canonical sort-key helpers.

- [ ] **Step 1: Write RED tests for public types, empty replay, duplicate themes, package timing, and non-empty market source refs**

Create tests/test_replay.py with:

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

- [ ] **Step 2: Run Task-1 tests and verify RED**

Run:

    pytest -q tests/test_replay.py

Expected: collection failure because decision_lab.replay does not exist.

- [ ] **Step 3: Implement replay types and validation helpers**

Create src/decision_lab/replay.py with:

    from __future__ import annotations

    from collections.abc import Sequence
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
        budget_config: ResearchBudgetConfig = field(
            default_factory=ResearchBudgetConfig
        )


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
        if effective_to is not None and cycle_date >= effective_to:
            return False
        return True


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


    def _universe_semantic_payload(universe) -> dict[str, object]:
        layers = sorted(universe.layers)
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
            "layers": layers,
            "candidates": candidates,
        }


    def _observation_sort_key(item: ThemeScanObservation) -> tuple[str, str, str, str]:
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

Task-1 run_replay_cycle may support the full validation shell plus empty execution; Task 2 fills non-empty orchestration. Use one private _validate_replay_input helper that:

- parses cycle date;
- rejects duplicate package.definition.theme_id;
- rejects blank package theme IDs;
- rejects blank market_source_ref;
- rejects inactive package definitions before any adapter call.

For an empty current replay, call existing rank_themes and allocator with empty current inputs so prior-history validation still runs, then construct deterministic hashes and no theme records.

- [ ] **Step 4: Run Task-1 tests and full regression**

Run:

    pytest -q tests/test_replay.py
    pytest -q

Expected: all Task-1 and existing tests pass.

- [ ] **Step 5: Commit**

    git add src/decision_lab/replay.py tests/test_replay.py
    git commit -m "feat: add replay cycle input boundary"

---

### Task 2: Pure orchestration, current theme records, NO_OBSERVATION, and unknown-theme routing

**Files:**
- Modify src/decision_lab/replay.py
- Modify tests/test_replay.py

**Interfaces:**
- Extends run_replay_cycle without changing its signature.
- Produces market_batches, combined_observations, scan_results, allocations, and ReplayThemeRecord tuples.
- No new downstream semantics are introduced.

- [ ] **Step 1: Add RED orchestration/status tests**

Append to tests/test_replay.py:

    from decision_lab.research_budget import ResearchTier
    from decision_lab.scanner import SupportDirection, ThemeScanObservation


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
        from decision_lab.research_budget import ResearchAllocation, ResearchTier

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

- [ ] **Step 2: Run Task-2 tests and verify RED**

Run:

    pytest -q tests/test_replay.py

Expected: new orchestration/status assertions fail while Task-1 validation remains green.

- [ ] **Step 3: Implement the orchestration pipeline**

Inside run_replay_cycle:

1. Validate ReplayCycleInput and package timing.
2. Canonical-sort ThemeReplayInput by theme_id.
3. For each theme input call adapt_market_observations exactly once.
4. Flatten market_batch.observations.
5. Add canonical-sorted external observations.
6. Canonical-sort combined observations with _observation_sort_key.
7. Build registry_state from supplied package.definition values only.
8. Canonical-sort prior scan results with _scan_sort_key.
9. Call rank_themes with combined observations and sorted prior scans.
10. Canonical-sort returned scan_results lexically by theme_id for the replay artifact.
11. Canonical-sort prior allocations with _allocation_sort_key.
12. Call ResearchBudgetAllocator().allocate.
13. Canonical-sort returned allocations lexically by theme_id for the replay artifact.
14. Build ReplayThemeRecord for the union of registered current themes and current external-observation theme IDs only.
15. Do not include prior-history-only theme IDs in theme_records.

Use lookup maps only after duplicate-producing components have already rejected invalid duplicates.

Theme record logic:

    current_theme_ids = sorted(
        registered_theme_ids | {obs.theme_id for obs in external_observations}
    )

    for theme_id in current_theme_ids:
        scan = scan_by_theme.get(theme_id)
        allocation = allocation_by_theme.get(theme_id)
        registered = theme_id in registered_theme_ids
        market_batch = batch_by_theme.get(theme_id)

        if scan is None:
            if allocation is not None:
                raise RuntimeError("allocation exists without scan result")
            status = ReplayStatus.NO_OBSERVATION
        else:
            if allocation is None:
                raise RuntimeError("scan result exists without allocation")
            status = ReplayStatus.ROUTED

Do not synthesize SCAN_ONLY for scan=None.

- [ ] **Step 4: Run Task-2 tests and full regression**

Run:

    pytest -q tests/test_replay.py
    pytest -q

Expected: PASS.

- [ ] **Step 5: Commit**

    git add src/decision_lab/replay.py tests/test_replay.py
    git commit -m "feat: orchestrate replay research routing"

---

### Task 3: Semantic input/result hashing and determinism boundaries

**Files:**
- Modify src/decision_lab/replay.py
- Modify tests/test_replay.py

**Interfaces:**
- Finalizes ReplayCycleResult.input_hash and result_hash.
- Adds no public API beyond Task 1.

- [ ] **Step 1: Add RED invariance/sensitivity tests**

Append helpers:

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
        from decision_lab.research_budget import ResearchAllocation, ResearchTier

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

Add imports:

    from dataclasses import asdict
    from decision_lab.ledger import canonical_hash

- [ ] **Step 2: Run Task-3 tests and verify RED**

Run:

    pytest -q tests/test_replay.py

Expected: hash-boundary tests fail until semantic payload construction is implemented.

- [ ] **Step 3: Implement semantic input hash**

After market_batches are known, construct registered theme semantic payloads:

    def _theme_replay_semantic_payload(
        theme_input: ThemeReplayInput,
        batch: MarketObservationBatch,
    ) -> dict[str, object]:
        package = theme_input.package
        return {
            "theme_id": package.definition.theme_id,
            "definition_semantic_hash": canonical_hash(
                _definition_semantic_payload(package.definition)
            ),
            "package_version": package.version,
            "universe_version": package.universe.version,
            "universe_semantic_hash": canonical_hash(
                _universe_semantic_payload(package.universe)
            ),
            "market_spec_hash": batch.spec_hash,
            "market_config_hash": batch.config_hash,
            "market_input_hash": batch.input_hash,
            "market_source_ref": theme_input.market_source_ref,
        }

Construct input_payload exactly:

    input_payload = {
        "cycle_as_of": replay_input.cycle_as_of,
        "registered_themes": [
            _theme_replay_semantic_payload(theme_input, batch_by_theme[theme_id])
            for theme_id, theme_input in canonical registered theme order
        ],
        "external_observations": [
            asdict(item) for item in sorted_external_observations
        ],
        "prior_scan_results": [
            asdict(item) for item in sorted_prior_scan_results
        ],
        "prior_allocations": [
            asdict(item) for item in sorted_prior_allocations
        ],
        "scanner_config": asdict(replay_input.scanner_config),
        "budget_config": asdict(replay_input.budget_config),
    }
    input_hash = canonical_hash(input_payload)

Do not include ThemeReplayInput.bars directly.

Do not include package.source_path or universe.generated_at.

- [ ] **Step 4: Implement result hash**

Construct the final result without result_hash first, then hash a separate payload:

    result_payload = {
        "cycle_as_of": cycle_as_of,
        "input_hash": input_hash,
        "market_batches": [asdict(x) for x in market_batches],
        "combined_observations": [asdict(x) for x in combined_observations],
        "scan_results": [asdict(x) for x in scan_results],
        "allocations": [asdict(x) for x in allocations],
        "theme_records": [asdict(x) for x in theme_records],
    }
    result_hash = canonical_hash(result_payload)

Return ReplayCycleResult with the computed hash.

- [ ] **Step 5: Run Task-3 tests and full regression**

Run:

    pytest -q tests/test_replay.py
    pytest -q

Expected: PASS.

- [ ] **Step 6: Commit**

    git add src/decision_lab/replay.py tests/test_replay.py
    git commit -m "feat: add semantic replay hashing"

---

### Task 4: End-to-end DataCenter, Genomics, Rates, no-observation acceptance fixture and public API

**Files:**
- Modify tests/test_replay.py
- Modify src/decision_lab/__init__.py

**Interfaces:**
- Uses existing config/themes/datacenter_infra.yaml.
- Uses existing config/themes/genomics_bio.yaml.
- Uses existing config/market_observations/datacenter_infra.yaml.
- Uses existing config/market_observations/genomics_bio.yaml.
- Uses existing config/adapters/market_observation_defaults.yaml.
- Exports replay interfaces from decision_lab package.

- [ ] **Step 1: Add RED real-package end-to-end fixture**

Append imports:

    from pathlib import Path

    from decision_lab.market_observation import (
        load_market_observation_config,
        load_market_observation_spec,
    )
    from decision_lab.themes import load_theme_package

    ROOT = Path(__file__).resolve().parents[1]

Add common eleven-session fixture:

    REPLAY_SESSIONS = (
        "2026-09-03",
        "2026-09-04",
        "2026-09-08",
        "2026-09-09",
        "2026-09-10",
        "2026-09-11",
        "2026-09-14",
        "2026-09-15",
        "2026-09-16",
        "2026-09-17",
        "2026-09-18",
    )


    def _series(symbol, closes):
        return tuple(
            MarketBar(
                symbol=symbol,
                session_date=session,
                available_at=f"{session}T21:00:00+00:00",
                close=close,
            )
            for session, close in zip(REPLAY_SESSIONS, closes, strict=True)
        )

DataCenter synthetic bars:

    def _datacenter_bars():
        benchmark = _series("SPY", [100] * 11)

        be = _series(
            "BE",
            [100, 102, 104, 106, 108, 110, 106, 102, 98, 94, 90],
        )
        nrg = _series(
            "NRG",
            [100, 101, 102, 103, 104, 105, 102, 99, 96, 93, 90],
        )
        ceg = _series(
            "CEG",
            [100, 102, 103, 105, 106, 108, 106, 103, 100, 98, 95],
        )
        return benchmark + be + nrg + ceg

Genomics proxy bars:

    def _genomics_bars():
        benchmark = _series("SPY", [100] * 11)
        arkg = _series(
            "ARKG",
            [100, 99, 98, 97, 96, 95, 100, 105, 110, 115, 120],
        )
        xbi = _series(
            "XBI",
            [100, 99, 98, 97, 96, 96, 96.2, 96.4, 96.6, 96.8, 97.0],
        )
        return benchmark + arkg + xbi

Create registered inputs:

    def _real_theme_inputs():
        market_config = load_market_observation_config(
            ROOT / "config/adapters/market_observation_defaults.yaml"
        )

        dc_package = load_theme_package(
            ROOT / "config/themes/datacenter_infra.yaml"
        )
        dc_spec = load_market_observation_spec(
            ROOT / "config/market_observations/datacenter_infra.yaml"
        )
        dc = ThemeReplayInput(
            package=dc_package,
            market_spec=dc_spec,
            market_config=market_config,
            bars=_datacenter_bars(),
            market_source_ref="fixture:e2e:datacenter",
        )

        bio_package = load_theme_package(
            ROOT / "config/themes/genomics_bio.yaml"
        )
        bio_spec = load_market_observation_spec(
            ROOT / "config/market_observations/genomics_bio.yaml"
        )
        bio = ThemeReplayInput(
            package=bio_package,
            market_spec=bio_spec,
            market_config=market_config,
            bars=_genomics_bars(),
            market_source_ref="fixture:e2e:genomics",
        )
        return dc, bio

Add DataCenter + Genomics + Rates + quiet registered theme test:

    def test_full_end_to_end_replay_separates_risk_opportunity_unknown_and_no_observation():
        dc, bio = _real_theme_inputs()
        quiet = _coverage_pending_theme_input("QuietTheme")

        result = run_replay_cycle(
            ReplayCycleInput(
                cycle_as_of="2026-09-19",
                themes=(bio, quiet, dc),
                external_observations=(
                    _radar_observation(
                        "DataCenter_Infra",
                        discovery=0.9,
                        novelty=0.8,
                    ),
                    _radar_observation(
                        "Genomics_Bio",
                        discovery=0.85,
                        novelty=0.75,
                    ),
                    _radar_observation(
                        "Rates",
                        discovery=0.8,
                        novelty=0.6,
                    ),
                ),
                prior_scan_results=(),
                prior_allocations=(),
                scanner_config=ScannerConfig(),
                budget_config=ResearchBudgetConfig(),
            )
        )

        records = {item.theme_id: item for item in result.theme_records}

        dc_record = records["DataCenter_Infra"]
        assert dc_record.replay_status is ReplayStatus.ROUTED
        assert dc_record.scan_result is not None
        assert dc_record.scan_result.forced_review
        assert dc_record.scan_result.independent_contradiction_count >= 1
        assert dc_record.allocation.tier is ResearchTier.FULL_DECISION_RESEARCH
        assert dc_record.allocation.forced_review

        bio_record = records["Genomics_Bio"]
        assert bio_record.replay_status is ReplayStatus.ROUTED
        assert bio_record.scan_result is not None
        assert bio_record.scan_result.independent_support_count >= 1
        assert bio_record.allocation.tier is ResearchTier.FULL_DECISION_RESEARCH
        assert not bio_record.allocation.forced_review
        assert not bio.package.theme_key_policy.evaluate(
            flow=1.0,
            structure=1.0,
            valid_sessions=100,
            permission="full",
        ).satisfied

        rates_record = records["Rates"]
        assert not rates_record.registered
        assert rates_record.allocation.tier is ResearchTier.SCAN_ONLY

        quiet_record = records["QuietTheme"]
        assert quiet_record.registered
        assert quiet_record.replay_status is ReplayStatus.NO_OBSERVATION
        assert quiet_record.scan_result is None
        assert quiet_record.allocation is None

        assert [x.theme_id for x in result.market_batches] == [
            "DataCenter_Infra",
            "Genomics_Bio",
            "QuietTheme",
        ]
        assert [x.theme_id for x in result.theme_records] == [
            "DataCenter_Infra",
            "Genomics_Bio",
            "QuietTheme",
            "Rates",
        ]


    def test_replay_does_not_mutate_real_packages_or_inputs():
        dc, bio = _real_theme_inputs()
        replay_input = ReplayCycleInput(
            cycle_as_of="2026-09-19",
            themes=(dc, bio),
            external_observations=(),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
        before = deepcopy(replay_input)

        run_replay_cycle(replay_input)

        assert replay_input == before


    def test_replay_interfaces_are_publicly_importable():
        import decision_lab

        for name in (
            "ReplayCycleInput",
            "ReplayCycleResult",
            "ReplayStatus",
            "ReplayThemeRecord",
            "ThemeReplayInput",
            "run_replay_cycle",
        ):
            assert getattr(decision_lab, name) is not None

- [ ] **Step 2: Run Task-4 tests and verify RED public-export failure only**

Run:

    pytest -q tests/test_replay.py

Expected before export: replay behavior tests pass; public import assertions fail because __init__.py does not export replay symbols.

If the end-to-end fixture itself fails, do not weaken gates or alter existing scanner/budget behavior. Inspect the synthetic bar fixture and only adjust fixture values when they do not actually satisfy the approved existing gates.

- [ ] **Step 3: Export replay public interfaces**

Modify src/decision_lab/__init__.py:

    from .replay import (
        ReplayCycleInput,
        ReplayCycleResult,
        ReplayStatus,
        ReplayThemeRecord,
        ThemeReplayInput,
        run_replay_cycle,
    )

Add all six names to sorted __all__.

Do not export private semantic-hash helpers.

- [ ] **Step 4: Run Task-4 tests and full regression**

Run:

    pytest -q tests/test_replay.py
    pytest -q

Expected: PASS.

- [ ] **Step 5: Commit**

    git add src/decision_lab/__init__.py tests/test_replay.py
    git commit -m "test: prove end-to-end replay routing"

---

### Task 5: Final safety audit, Ruff, and whole-branch review

**Files:**
- Verify src/decision_lab/replay.py
- Verify src/decision_lab/__init__.py
- Verify tests/test_replay.py
- Review-only all forbidden downstream modules

**Interfaces:**
- Produces verification evidence only.
- No new behavior.

- [ ] **Step 1: Run fresh full regression**

Run:

    pytest -q

Expected: all tests PASS.

- [ ] **Step 2: Run changed-files Ruff**

Run:

    python -m ruff check       src/decision_lab/replay.py       src/decision_lab/__init__.py       tests/test_replay.py

Expected: exit 0.

- [ ] **Step 3: Audit forbidden semantic drift**

Verify no diffs to:

    src/decision_lab/market_observation.py
    src/decision_lab/scanner.py
    src/decision_lab/research_budget.py
    src/decision_lab/themes.py
    src/decision_lab/universe.py
    src/decision_lab/tape.py
    src/decision_lab/playbooks.py
    src/decision_lab/hierarchical.py
    src/decision_lab/ledger.py

Verify final PR contains no persistent new .github/workflows file.

Verify replay.py contains none of these imports/calls:

    requests
    urllib
    httpx
    yfinance
    alpaca
    polygon
    pathlib.Path
    open(
    write_immutable_json
    datetime.now
    random
    uuid

datetime parsing imports are allowed; ambient time calls are not.

- [ ] **Step 4: Whole-branch review against Review Focus**

Inspect specifically:

- prior-only theme IDs never enter current theme_records;
- duplicate current registered themes fail before market adapter execution;
- cycle timestamp normalization to UTC is correct;
- package effective_to remains half-open;
- registered coverage pending/no external is NO_OBSERVATION;
- registered coverage pending + model evidence is real routed SCAN_ONLY;
- unknown model-only theme is real routed SCAN_ONLY;
- scan without allocation or allocation without scan cannot silently appear;
- package.source_path, universe.generated_at, display/annotation-only fields are excluded from input_hash;
- used market bars/effective dates/provenance/lifecycle/config/history are included;
- result_hash has no self-reference;
- no input object mutation;
- no filesystem/network/action side effects.

Any Critical/Important issue gets one TDD fix pass:

1. write reproducing RED test;
2. verify RED;
3. implement minimal fix;
4. rerun tests;
5. rerun Ruff.

- [ ] **Step 5: Exact-final-tree verification**

On exact final branch head:

    pytest -q
    python -m ruff check       src/decision_lab/replay.py       src/decision_lab/__init__.py       tests/test_replay.py

Record exact pytest count/time and Ruff result.

- [ ] **Step 6: Keep branch unmerged**

Present integration options after exact-final-tree verification. Do not merge until explicit user authorization.
