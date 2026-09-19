# World Scanner & Research Budget Funnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, fail-closed World Scanner and research-budget allocator that routes only independently corroborated strengthening themes into expensive research while preserving existing ThemeKey/Tape/router/ledger semantics.

**Architecture:** Add `scanner.py` for typed cheap observations, deterministic aggregation, confidence/priority diagnostics, lifecycle recommendations, prior-only decay, and forced-review detection. Add `research_budget.py` for capacity-limited tier allocation with forced-review preemption. Both modules consume read-only mappings of currently effective `ThemeDefinition` objects; neither mutates `ThemeRegistry` or action-permission state.

**Tech Stack:** Python 3.11, dataclasses, Enum, Mapping/Iterable typing, PyYAML, pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-19-world-scanner-research-budget-funnel-design.md`

## Global Constraints

- Radar/model observations are structurally distinct from independent evidence.
- Strong model-only evidence cannot receive ordinary `THEME_RESEARCH` or `FULL_DECISION_RESEARCH`.
- `rank_themes(...)` emits lifecycle recommendations only; it never mutates `ThemeRegistry`.
- Only observations with `observation.as_of <= cycle_as_of` are valid.
- Only prior results with `prior.as_of < cycle_as_of` may affect historical features.
- Missing positive components remain `None`; they are omitted from weighted means rather than imputed.
- `FULL_DECISION_RESEARCH` consumes one theme-research slot and one full-decision slot.
- Forced review consumes the same capacity and preempts ordinary allocation; it does not create extra capacity.
- Unknown themes may be scanned but cannot enter package-dependent expensive research.
- Theme calibration state does not control research allocation; an uncalibrated theme can be deeply researched while ThemeKey remains false.
- No changes to Tape, A-H router, hierarchical linkage, ThemeKey semantics, or ledger schema.
- No live/private ledger logging, scheduling, portfolio sizing, or brokerage execution.
- Shipped v0.1 weights/gates are labeled `uncalibrated` research-routing defaults.

## Review Focus

1. **Duplicate evidence from the same independent source** must not inflate `independent_support_count`; count distinct independent `source_ref` values, not observation rows. Task 1 adds a regression test.
2. **Mixed naive/offset timestamps** must compare safely and deterministically by normalizing all ISO timestamps through one UTC parser. Task 1 adds a timezone-equivalence test.
3. **All-positive components missing** must not produce NaN or accidental promotion; priority must deterministically fall back to 0.0. Task 1 adds a missing-components test.
4. **Forced-review demand larger than capacity** must not exceed slot caps; severity/priority/confidence/theme_id order must choose the admitted subset. Task 3 adds an over-capacity forced-review test.
5. **A FULL_DECISION_RESEARCH allocation must not consume two theme slots accidentally in addition to its one intended theme slot**; total allocated non-scan themes must never exceed `theme_research_slots`. Task 3 adds an accounting regression test.

---

## File map

- Create `src/decision_lab/scanner.py`: scanner data classes, config, timestamp normalization, aggregation, history validation, lifecycle recommendation, priority, forced review, deterministic ranking, config loading.
- Create `src/decision_lab/research_budget.py`: research tiers, allocation data class, budget config, deterministic forced/ordinary allocation, config loading.
- Create `config/scanner/world_scanner_defaults.yaml`: uncalibrated v0.1 scanner/source/priority/lifecycle defaults.
- Create `config/policies/research_budget_defaults.yaml`: uncalibrated capacity/promotion defaults.
- Create `tests/test_scanner.py`: scanner validation, scoring, history, lifecycle, provenance, determinism, registry immutability.
- Create `tests/test_research_budget.py`: independent-corroboration promotion, slot accounting, forced preemption, unknown-theme blocking, tie-breaks, ThemeKey separation.
- Modify `src/decision_lab/__init__.py`: public exports only.
- Modify `README.md`: replace the stale “no second live theme/global scanner yet” text with the implemented Increment-3 architecture after code is green.
- Do not modify `src/decision_lab/tape.py`, `playbooks.py`, `hierarchical.py`, `themes.py`, or `ledger.py` unless a regression proves an unavoidable direct defect. Any such need upgrades scope and stops implementation.

---

### Task 1: Scanner typed interfaces, validation, aggregation, confidence, and priority

**Files:**
- Create: `src/decision_lab/scanner.py`
- Create: `tests/test_scanner.py`

**Interfaces:**
- Consumes:
  - `decision_lab.evidence.SourceType`
  - `decision_lab.ledger.canonical_hash(payload) -> str`
  - `decision_lab.themes.ThemeDefinition`
- Produces:
  - `SupportDirection(str, Enum)`
  - `ThemeScanObservation`
  - `ScannerConfig`
  - `ThemeScanResult`
  - `rank_themes(observations, registry_state, prior_results, config, cycle_as_of) -> list[ThemeScanResult]`
  - `load_scanner_config(path) -> ScannerConfig`

- [ ] **Step 1: Write RED tests for typed observations, future-date rejection, source distinction, duplicate-source counting, timezone normalization, missingness, and basic priority**

Create `tests/test_scanner.py` with these initial tests:

```python
from copy import deepcopy

import pytest

from decision_lab.scanner import (
    ScannerConfig,
    SupportDirection,
    ThemeScanObservation,
    rank_themes,
)
from decision_lab.themes import ThemeDefinition, ThemeLifecycleState


def _registry():
    return {
        "DataCenter_Infra": ThemeDefinition(
            theme_id="DataCenter_Infra",
            display_name="Data Center Infrastructure",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            effective_from="2026-09-01",
            version="1",
        ),
        "Genomics_Bio": ThemeDefinition(
            theme_id="Genomics_Bio",
            display_name="Genomics and Biotechnology",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            effective_from="2026-09-18",
            version="1",
        ),
    }


def _obs(
    *,
    theme_id="DataCenter_Infra",
    as_of="2026-09-19T15:00:00+00:00",
    source_type="market_data",
    source_ref="market:theme-breadth",
    independent=True,
    support=SupportDirection.SUPPORTING,
    discovery=0.8,
    structure=0.7,
    persistence=0.7,
    breadth=0.7,
    relative_strength=0.7,
    novelty=0.5,
):
    return ThemeScanObservation(
        theme_id=theme_id,
        as_of=as_of,
        source_type=source_type,
        source_ref=source_ref,
        discovery_signal=discovery,
        structure_signal=structure,
        persistence_signal=persistence,
        breadth_signal=breadth,
        relative_strength_signal=relative_strength,
        novelty_signal=novelty,
        support_direction=support,
        evidence_refs=(source_ref,),
        is_independent=independent,
        observed_or_inferred="observed",
    )


def test_future_dated_observation_is_rejected():
    with pytest.raises(ValueError, match="future-dated observation"):
        rank_themes(
            [_obs(as_of="2026-09-20T00:00:00+00:00")],
            _registry(),
            (),
            ScannerConfig(),
            cycle_as_of="2026-09-19T23:59:59+00:00",
        )


def test_radar_observation_cannot_claim_independent_status():
    bad = _obs(
        source_type="radar_model_output",
        source_ref="radar:run-1",
        independent=True,
    )
    with pytest.raises(ValueError, match="radar_model_output cannot be independent"):
        rank_themes(
            [bad],
            _registry(),
            (),
            ScannerConfig(),
            cycle_as_of="2026-09-19T23:59:59+00:00",
        )


def test_duplicate_independent_source_ref_counts_once():
    observations = [
        _obs(source_ref="market:breadth", breadth=0.8),
        _obs(source_ref="market:breadth", breadth=0.9, novelty=0.6),
    ]

    result = rank_themes(
        observations,
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )[0]

    assert result.independent_support_count == 1


def test_naive_and_offset_timestamps_normalize_to_same_cycle():
    observations = [
        _obs(as_of="2026-09-19T15:00:00", source_ref="market:naive"),
        _obs(as_of="2026-09-19T11:00:00-04:00", source_ref="market:offset"),
    ]

    result = rank_themes(
        observations,
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T15:00:00+00:00",
    )[0]

    assert result.independent_support_count == 2


def test_missing_components_remain_none_and_priority_is_finite_zero():
    observation = ThemeScanObservation(
        theme_id="DataCenter_Infra",
        as_of="2026-09-19",
        source_type="market_data",
        source_ref="market:empty",
        support_direction=SupportDirection.NEUTRAL,
        evidence_refs=("market:empty",),
        is_independent=True,
        observed_or_inferred="observed",
    )

    result = rank_themes(
        [observation],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.discovery_score is None
    assert result.structural_score is None
    assert result.breadth_score is None
    assert result.research_priority == 0.0


def test_model_and_independent_sources_are_aggregated_but_counted_separately():
    observations = [
        _obs(
            source_type="radar_model_output",
            source_ref="radar:run-1",
            independent=False,
            discovery=1.0,
            structure=0.9,
        ),
        _obs(
            source_type="market_data",
            source_ref="market:breadth",
            independent=True,
            discovery=0.6,
            structure=0.6,
        ),
    ]

    result = rank_themes(
        observations,
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )[0]

    assert result.discovery_score is not None
    assert result.structural_score is not None
    assert result.independent_support_count == 1
    assert result.independent_contradiction_count == 0
    assert 0.0 <= result.evidence_confidence <= 1.0
    assert 0.0 <= result.research_priority <= 1.0


def test_independent_support_raises_priority_over_model_only_evidence():
    radar = _obs(
        source_type="radar_model_output",
        source_ref="radar:run-1",
        independent=False,
        discovery=0.9,
        structure=0.8,
        persistence=0.8,
        breadth=0.8,
        relative_strength=0.8,
        novelty=0.5,
    )
    independent = _obs(
        source_type="market_data",
        source_ref="market:breadth",
        independent=True,
        discovery=0.9,
        structure=0.8,
        persistence=0.8,
        breadth=0.8,
        relative_strength=0.8,
        novelty=0.5,
    )

    model_only = rank_themes(
        [radar],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )[0]
    corroborated = rank_themes(
        [radar, independent],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )[0]

    assert model_only.independent_support_count == 0
    assert corroborated.independent_support_count == 1
    assert corroborated.evidence_confidence > model_only.evidence_confidence
    assert corroborated.research_priority > model_only.research_priority


def test_stale_independent_evidence_lowers_confidence_and_priority():
    fresh = rank_themes(
        [_obs(as_of="2026-09-19", source_ref="market:fresh")],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]
    stale = rank_themes(
        [_obs(as_of="2026-09-09", source_ref="market:stale")],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert stale.evidence_confidence < fresh.evidence_confidence
    assert stale.research_priority < fresh.research_priority


def test_scanner_does_not_mutate_registry_state():
    registry = _registry()
    before = deepcopy(registry)

    rank_themes(
        [_obs()],
        registry,
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )

    assert registry == before
```

- [ ] **Step 2: Run the scanner tests and verify RED**

Run:

```bash
pytest -q tests/test_scanner.py
```

Expected: collection failure because `decision_lab.scanner` does not exist.

- [ ] **Step 3: Implement the scanner data classes, config defaults, UTC parser, validation, weighted aggregation, confidence, and base priority**

Create `src/decision_lab/scanner.py` with this exact public shape:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Literal, Mapping

import yaml

from .evidence import SourceType
from .ledger import canonical_hash
from .themes import ThemeDefinition


class SupportDirection(str, Enum):
    SUPPORTING = "supporting"
    NEUTRAL = "neutral"
    CONTRADICTING = "contradicting"


@dataclass(frozen=True)
class ThemeScanObservation:
    theme_id: str
    as_of: str
    source_type: SourceType
    source_ref: str
    discovery_signal: float | None = None
    structure_signal: float | None = None
    persistence_signal: float | None = None
    breadth_signal: float | None = None
    relative_strength_signal: float | None = None
    volatility_signal: float | None = None
    novelty_signal: float | None = None
    support_direction: SupportDirection = SupportDirection.NEUTRAL
    evidence_refs: tuple[str, ...] = ()
    is_independent: bool = False
    observed_or_inferred: Literal["observed", "inferred"] = "observed"
    notes: str | None = None


@dataclass(frozen=True)
class ScannerConfig:
    version: str = "0.1"
    calibration_label: str = "uncalibrated"
    stale_after_days: int = 5
    source_weights: Mapping[str, float] = field(default_factory=lambda: {
        "sec_filing": 1.00,
        "company_ir": 1.00,
        "official_macro": 1.00,
        "industry_primary": 0.95,
        "market_data": 0.90,
        "reputable_reporting": 0.75,
        "derived_feature": 0.60,
        "radar_model_output": 0.50,
    })
    component_weights: Mapping[str, float] = field(default_factory=lambda: {
        "discovery": 0.15,
        "structural": 0.20,
        "persistence": 0.15,
        "breadth": 0.10,
        "relative_strength": 0.10,
        "novelty": 0.15,
        "evidence_confidence": 0.15,
    })
    contradiction_staleness_penalty: float = 0.25
    strengthening_structure_gate: float = 0.60
    strengthening_persistence_gate: float = 0.60
    weakening_low_persistence_gate: float = 0.35
    weakening_low_breadth_gate: float = 0.35
    hard_contradiction_ratio: float = 0.50
    dormant_no_support_cycles: int = 3
    novelty_floor: float = 0.20
    repeated_no_change_penalty_per_cycle: float = 0.10
    repeated_no_change_penalty_cap: float = 0.30


@dataclass(frozen=True)
class ThemeScanResult:
    theme_id: str
    as_of: str
    discovery_score: float | None
    structural_score: float | None
    persistence_score: float | None
    breadth_score: float | None
    relative_strength_score: float | None
    novelty_score: float | None
    evidence_confidence: float
    independent_support_count: int
    independent_contradiction_count: int
    lifecycle_recommendation: str
    research_priority: float
    forced_review: bool
    forced_review_severity: int
    forced_review_reasons: tuple[str, ...]
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    config_hash: str
    registry_version: str | None
    prior_result_refs: tuple[str, ...]


def load_scanner_config(path: str | Path) -> ScannerConfig:
    payload = yaml.safe_load(Path(path).read_text())
    payload = dict(payload)
    payload.pop("calibration_label", None)
    source_weights = payload.pop("source_weights", None)
    component_weights = payload.pop("component_weights", None)
    return ScannerConfig(
        calibration_label="uncalibrated",
        source_weights=source_weights or ScannerConfig().source_weights,
        component_weights=component_weights or ScannerConfig().component_weights,
        **payload,
    )
```

Implement private helpers with these behaviors:

```python
def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _validate_observation(obs, cycle_dt):
    if _parse_utc(obs.as_of) > cycle_dt:
        raise ValueError("future-dated observation")
    if obs.source_type == "radar_model_output" and obs.is_independent:
        raise ValueError("radar_model_output cannot be independent")
    for name in (
        "discovery_signal",
        "structure_signal",
        "persistence_signal",
        "breadth_signal",
        "relative_strength_signal",
        "volatility_signal",
        "novelty_signal",
    ):
        value = getattr(obs, name)
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be in [0,1]")
```

Aggregate component values with the source-class weight for each observation. If a component has no values, return `None`.

Count independent support/contradiction by distinct `source_ref`, not observation row.

Compute:

```python
coverage = min(1.0, independent_source_count / 2.0)
agreement = 1.0 - independent_contradiction_count / max(
    1, independent_support_count + independent_contradiction_count
)
freshness = mean(max(0.0, 1.0 - age_days / stale_after_days)) over independent observations
evidence_confidence = 0.0 if no independent observations else (
    0.40 * coverage + 0.30 * agreement + 0.30 * freshness
)
```

For Task 1 only, set:

```python
lifecycle_recommendation = "no_change"
forced_review = False
forced_review_severity = 0
forced_review_reasons = ()
repeated_no_change_penalty = 0.0
```

Compute weighted mean across non-`None` positive components. If none exist, `base_priority = 0.0`.

Treat an observation as stale when its normalized age is strictly greater than `config.stale_after_days`. Compute `stale_ratio = stale_observation_count / max(1, total_observation_count)` across all observations for the theme. Compute contradiction/staleness penalty and final priority exactly per spec. Use `canonical_hash(asdict(config))` for `config_hash`.

Return results sorted by:

```python
(-research_priority, -evidence_confidence, theme_id)
```

Task 2 will extend lifecycle/history/forced-review ordering.

- [ ] **Step 4: Run scanner tests and verify GREEN**

Run:

```bash
pytest -q tests/test_scanner.py
```

Expected: all Task-1 scanner tests PASS.

- [ ] **Step 5: Run the complete existing suite**

Run:

```bash
pytest -q
```

Expected: all existing tests plus Task-1 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/decision_lab/scanner.py tests/test_scanner.py
git commit -m "feat: add deterministic theme scanner core"
```

---

### Task 2: Prior-only history, lifecycle recommendations, repeated-no-change decay, forced-review diagnostics, and deterministic ranking

**Files:**
- Modify: `src/decision_lab/scanner.py`
- Modify: `tests/test_scanner.py`

**Interfaces:**
- Consumes: `ThemeScanObservation`, `ScannerConfig`, `ThemeScanResult`, `rank_themes(...)` from Task 1.
- Produces: complete scanner semantics required by the spec; signature remains unchanged.

- [ ] **Step 1: Add RED tests for prior-date safety, lifecycle recommendation, repeated-no-change decay, contradiction forced review, forced-review decay bypass, unknown themes, and deterministic output**

Append:

```python
def _prior(theme_id, as_of, *, novelty=0.05, priority=0.70):
    return ThemeScanResult(
        theme_id=theme_id,
        as_of=as_of,
        discovery_score=0.7,
        structural_score=0.7,
        persistence_score=0.7,
        breadth_score=0.7,
        relative_strength_score=0.7,
        novelty_score=novelty,
        evidence_confidence=0.7,
        independent_support_count=1,
        independent_contradiction_count=0,
        lifecycle_recommendation="no_change",
        research_priority=priority,
        forced_review=False,
        forced_review_severity=0,
        forced_review_reasons=(),
        reasons=(),
        evidence_refs=(f"prior:{as_of}",),
        config_hash="prior-config",
        registry_version="1",
        prior_result_refs=(),
    )


def test_same_or_future_cycle_prior_result_is_rejected():
    with pytest.raises(ValueError, match="prior scan result must be strictly earlier"):
        rank_themes(
            [_obs()],
            _registry(),
            [_prior("DataCenter_Infra", "2026-09-19T23:59:59+00:00")],
            ScannerConfig(),
            cycle_as_of="2026-09-19T23:59:59+00:00",
        )


def test_discovery_or_forming_theme_can_recommend_strengthening_without_registry_mutation():
    registry = {
        "New_Theme": ThemeDefinition(
            theme_id="New_Theme",
            display_name="New Theme",
            lifecycle_state=ThemeLifecycleState.FORMING,
            version="1",
        )
    }
    observation = _obs(
        theme_id="New_Theme",
        source_ref="market:new",
        structure=0.75,
        persistence=0.75,
    )

    before = deepcopy(registry)
    result = rank_themes(
        [observation],
        registry,
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )[0]

    assert result.lifecycle_recommendation == "strengthening"
    assert registry == before
    assert registry["New_Theme"].lifecycle_state is ThemeLifecycleState.FORMING


def test_hard_independent_contradiction_forces_review_and_recommends_weakening():
    contradiction = _obs(
        support=SupportDirection.CONTRADICTING,
        source_ref="official:contradiction",
        structure=0.2,
        persistence=0.2,
        breadth=0.2,
        relative_strength=0.2,
        novelty=0.9,
    )

    result = rank_themes(
        [contradiction],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )[0]

    assert result.lifecycle_recommendation == "weakening"
    assert result.forced_review
    assert result.forced_review_severity > 0
    assert "independent contradiction" in result.forced_review_reasons


def test_repeated_no_change_prior_cycles_reduce_ordinary_priority():
    priors = [
        _prior("DataCenter_Infra", "2026-09-16", novelty=0.05),
        _prior("DataCenter_Infra", "2026-09-17", novelty=0.05),
        _prior("DataCenter_Infra", "2026-09-18", novelty=0.05),
    ]

    without_history = rank_themes(
        [_obs(novelty=0.05)],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]
    with_history = rank_themes(
        [_obs(novelty=0.05)],
        _registry(),
        priors,
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert with_history.research_priority < without_history.research_priority
    assert len(with_history.prior_result_refs) == 3


def test_forced_review_is_not_suppressed_by_repeated_no_change_decay():
    priors = [
        _prior("DataCenter_Infra", "2026-09-16", novelty=0.05),
        _prior("DataCenter_Infra", "2026-09-17", novelty=0.05),
        _prior("DataCenter_Infra", "2026-09-18", novelty=0.05),
    ]
    contradiction = _obs(
        support=SupportDirection.CONTRADICTING,
        source_ref="official:break",
        novelty=0.9,
    )

    result = rank_themes(
        [contradiction],
        _registry(),
        priors,
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.forced_review


def test_unknown_theme_is_scanned_as_discovery_candidate_without_registry_version():
    observation = _obs(theme_id="Unknown_Theme", source_ref="market:unknown")

    result = rank_themes(
        [observation],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.theme_id == "Unknown_Theme"
    assert result.registry_version is None
    assert result.lifecycle_recommendation == "discovery"


def test_scanner_output_order_is_deterministic_for_equal_inputs():
    observations = [
        _obs(theme_id="Z_Theme", source_ref="market:z"),
        _obs(theme_id="A_Theme", source_ref="market:a"),
    ]

    first = rank_themes(
        observations,
        {},
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )
    second = rank_themes(
        list(reversed(observations)),
        {},
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )

    assert [item.theme_id for item in first] == ["A_Theme", "Z_Theme"]
    assert first == second
```

- [ ] **Step 2: Run scanner tests and verify RED**

Run:

```bash
pytest -q tests/test_scanner.py
```

Expected: new history/lifecycle/forced-review tests FAIL while Task-1 tests remain green.

- [ ] **Step 3: Implement strictly prior history, lifecycle recommendations, decay, forced review, and final ranking**

Extend `rank_themes`:

1. Normalize `cycle_as_of` once with `_parse_utc`.
2. For every prior result:
   - if `_parse_utc(prior.as_of) >= cycle_dt`, raise `ValueError("prior scan result must be strictly earlier")`;
   - group by `theme_id`;
   - sort each theme's priors by normalized timestamp.
3. Consecutive no-change cycles:
   - walk backward over a theme's sorted priors;
   - stop at first prior with `novelty_score is None or novelty_score >= config.novelty_floor`;
   - count only consecutive low-novelty priors;
   - compute `min(cap, per_cycle * count)`.
4. Forced review:
   - independent contradiction ratio >= `hard_contradiction_ratio` -> severity 3, reason `"independent contradiction"`;
   - current effective state in strengthening/mature plus low persistence+low breadth -> severity 2, reason `"lifecycle deterioration"`;
   - future forced-review source kinds such as Tape transitions remain deferred because Increment 3 has no Tape-event input field.
5. Lifecycle recommendation:
   - unknown theme -> `"discovery"`;
   - discovery/forming + independent support >=1 + structural >=0.60 + persistence >=0.60 + no contradiction -> `"strengthening"`;
   - strengthening/mature + hard contradiction -> `"weakening"`;
   - strengthening/mature + persistence<0.35 + breadth<0.35 -> `"weakening"`;
   - weakening + current plus last 3 strictly prior cycles have zero independent support -> `"dormant"`;
   - otherwise `"no_change"`;
   - never emit `"retired"`.
6. When `forced_review=True`, repeated-no-change penalty may still be reported in reasons but must not block the forced flag.
7. Set `prior_result_refs` to deterministic hashes:
   `canonical_hash(asdict(prior))` for the actual priors consumed.
8. Sort final scanner results by:
   ```python
   (
       not item.forced_review,
       -item.forced_review_severity,
       -item.research_priority,
       -item.evidence_confidence,
       item.theme_id,
   )
   ```

- [ ] **Step 4: Run scanner tests and verify GREEN**

Run:

```bash
pytest -q tests/test_scanner.py
```

Expected: all scanner tests PASS.

- [ ] **Step 5: Run the complete suite**

Run:

```bash
pytest -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/decision_lab/scanner.py tests/test_scanner.py
git commit -m "feat: add scanner lifecycle and forced-review semantics"
```

---

### Task 3: Research budget allocator, capacity accounting, independent-corroboration gate, forced-review preemption, and ThemeKey separation

**Files:**
- Create: `src/decision_lab/research_budget.py`
- Create: `tests/test_research_budget.py`

**Interfaces:**
- Consumes:
  - `ThemeScanResult`
  - `ThemeDefinition`
  - `canonical_hash`
- Produces:
  - `ResearchTier(str, Enum)`
  - `ResearchAllocation`
  - `ResearchBudgetConfig`
  - `ResearchBudgetAllocator.allocate(scan_results, registry_state, config, cycle_as_of) -> list[ResearchAllocation]`
  - `load_research_budget_config(path) -> ResearchBudgetConfig`

- [ ] **Step 1: Write RED allocator tests**

Create `tests/test_research_budget.py`:

```python
from dataclasses import replace

from decision_lab.research_budget import (
    ResearchBudgetAllocator,
    ResearchBudgetConfig,
    ResearchTier,
)
from decision_lab.scanner import ThemeScanResult
from decision_lab.themes import (
    ThemeCalibrationState,
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemeLifecycleState,
)


def _registry():
    return {
        "DataCenter_Infra": ThemeDefinition(
            theme_id="DataCenter_Infra",
            display_name="Data Center Infrastructure",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            version="1",
        ),
        "Genomics_Bio": ThemeDefinition(
            theme_id="Genomics_Bio",
            display_name="Genomics and Biotechnology",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            version="1",
        ),
    }


def _scan(
    theme_id,
    *,
    priority=0.80,
    confidence=0.70,
    novelty=0.50,
    independent_support=1,
    contradictions=0,
    forced=False,
    severity=0,
):
    return ThemeScanResult(
        theme_id=theme_id,
        as_of="2026-09-19",
        discovery_score=0.8,
        structural_score=0.8,
        persistence_score=0.8,
        breadth_score=0.8,
        relative_strength_score=0.8,
        novelty_score=novelty,
        evidence_confidence=confidence,
        independent_support_count=independent_support,
        independent_contradiction_count=contradictions,
        lifecycle_recommendation="no_change",
        research_priority=priority,
        forced_review=forced,
        forced_review_severity=severity,
        forced_review_reasons=("forced",) if forced else (),
        reasons=(),
        evidence_refs=(f"scan:{theme_id}",),
        config_hash="scanner-config",
        registry_version="1",
        prior_result_refs=(),
    )


def test_model_only_strength_remains_scan_only():
    result = ResearchBudgetAllocator().allocate(
        [_scan("DataCenter_Infra", independent_support=0)],
        _registry(),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.tier is ResearchTier.SCAN_ONLY
    assert "independent corroboration missing" in result.allocation_reasons


def test_strengthening_theme_with_independent_support_can_enter_theme_research():
    scan = _scan("DataCenter_Infra", priority=0.55, novelty=0.20)

    result = ResearchBudgetAllocator().allocate(
        [scan],
        _registry(),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.tier is ResearchTier.THEME_RESEARCH


def test_high_priority_novel_strengthening_theme_can_enter_full_research():
    result = ResearchBudgetAllocator().allocate(
        [_scan("DataCenter_Infra", priority=0.80, novelty=0.50)],
        _registry(),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.tier is ResearchTier.FULL_DECISION_RESEARCH


def test_unknown_theme_never_enters_package_dependent_research():
    result = ResearchBudgetAllocator().allocate(
        [_scan("Unknown_Theme", priority=1.0, novelty=1.0, forced=True, severity=3)],
        _registry(),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.tier is ResearchTier.SCAN_ONLY
    assert "theme not registered" in result.allocation_reasons


def test_forced_review_preempts_lower_priority_ordinary_full_slot():
    config = ResearchBudgetConfig(theme_research_slots=2, full_decision_slots=1)
    forced = _scan("Genomics_Bio", priority=0.40, novelty=0.10, forced=True, severity=3)
    ordinary = _scan("DataCenter_Infra", priority=0.95, novelty=0.90)

    results = ResearchBudgetAllocator().allocate(
        [ordinary, forced],
        _registry(),
        config,
        cycle_as_of="2026-09-19",
    )
    by_theme = {item.theme_id: item for item in results}

    assert by_theme["Genomics_Bio"].tier is ResearchTier.FULL_DECISION_RESEARCH
    assert by_theme["DataCenter_Infra"].tier is ResearchTier.THEME_RESEARCH


def test_forced_review_over_capacity_respects_caps_and_deterministic_order():
    registry = {
        name: ThemeDefinition(
            theme_id=name,
            display_name=name,
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            version="1",
        )
        for name in ("A", "B", "C")
    }
    scans = [
        _scan("C", forced=True, severity=2, priority=0.9),
        _scan("B", forced=True, severity=3, priority=0.7),
        _scan("A", forced=True, severity=3, priority=0.8),
    ]
    config = ResearchBudgetConfig(theme_research_slots=2, full_decision_slots=2)

    results = ResearchBudgetAllocator().allocate(
        scans,
        registry,
        config,
        cycle_as_of="2026-09-19",
    )
    full = [item.theme_id for item in results if item.tier is ResearchTier.FULL_DECISION_RESEARCH]

    assert full == ["A", "B"]


def test_full_research_consumes_exactly_one_theme_slot():
    registry = {
        name: ThemeDefinition(
            theme_id=name,
            display_name=name,
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            version="1",
        )
        for name in ("A", "B", "C")
    }
    scans = [_scan("A"), _scan("B"), _scan("C")]
    config = ResearchBudgetConfig(theme_research_slots=2, full_decision_slots=2)

    results = ResearchBudgetAllocator().allocate(
        scans,
        registry,
        config,
        cycle_as_of="2026-09-19",
    )
    expensive = [item for item in results if item.tier is not ResearchTier.SCAN_ONLY]

    assert len(expensive) == 2


def test_uncalibrated_themekey_does_not_block_research_or_become_satisfied():
    scan = _scan("Genomics_Bio", priority=0.90, novelty=0.80)

    allocation = ResearchBudgetAllocator().allocate(
        [scan],
        _registry(),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    policy = ThemeKeyPolicy(
        calibration_state=ThemeCalibrationState.UNCALIBRATED,
        minimum_flow=0.50,
    )
    theme_key = policy.evaluate(
        flow=1.0,
        structure=1.0,
        valid_sessions=100,
        permission="probe",
    )

    assert allocation.tier is ResearchTier.FULL_DECISION_RESEARCH
    assert not theme_key.satisfied


def test_stale_scanner_confidence_can_block_ordinary_promotion():
    from decision_lab.scanner import (
        ScannerConfig,
        SupportDirection,
        ThemeScanObservation,
        rank_themes,
    )

    stale_observation = ThemeScanObservation(
        theme_id="DataCenter_Infra",
        as_of="2026-09-09",
        source_type="market_data",
        source_ref="market:stale",
        discovery_signal=0.9,
        structure_signal=0.9,
        persistence_signal=0.9,
        breadth_signal=0.9,
        relative_strength_signal=0.9,
        novelty_signal=0.9,
        support_direction=SupportDirection.SUPPORTING,
        evidence_refs=("market:stale",),
        is_independent=True,
        observed_or_inferred="observed",
    )
    stale_scan = rank_themes(
        [stale_observation],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    allocation = ResearchBudgetAllocator().allocate(
        [stale_scan],
        _registry(),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert stale_scan.evidence_confidence < ResearchBudgetConfig().confidence_floor
    assert allocation.tier is ResearchTier.SCAN_ONLY
    assert "evidence confidence below floor" in allocation.allocation_reasons


def test_allocator_tie_break_is_deterministic():
    registry = {
        name: ThemeDefinition(
            theme_id=name,
            display_name=name,
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            version="1",
        )
        for name in ("A", "B")
    }
    scans = [_scan("B"), _scan("A")]

    first = ResearchBudgetAllocator().allocate(
        scans,
        registry,
        ResearchBudgetConfig(theme_research_slots=1, full_decision_slots=1),
        cycle_as_of="2026-09-19",
    )
    second = ResearchBudgetAllocator().allocate(
        list(reversed(scans)),
        registry,
        ResearchBudgetConfig(theme_research_slots=1, full_decision_slots=1),
        cycle_as_of="2026-09-19",
    )

    assert first == second
    assert first[0].theme_id == "A"
```

- [ ] **Step 2: Run allocator tests and verify RED**

Run:

```bash
pytest -q tests/test_research_budget.py
```

Expected: collection failure because `decision_lab.research_budget` does not exist.

- [ ] **Step 3: Implement allocator types/config and capacity-safe deterministic allocation**

Create `src/decision_lab/research_budget.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from .ledger import canonical_hash
from .scanner import ThemeScanResult, _parse_utc
from .themes import ThemeDefinition, ThemeLifecycleState


class ResearchTier(str, Enum):
    SCAN_ONLY = "SCAN_ONLY"
    THEME_RESEARCH = "THEME_RESEARCH"
    FULL_DECISION_RESEARCH = "FULL_DECISION_RESEARCH"


@dataclass(frozen=True)
class ResearchAllocation:
    theme_id: str
    as_of: str
    tier: ResearchTier
    priority: float
    forced_review: bool
    allocation_reasons: tuple[str, ...]
    source_scan_result_hash: str


@dataclass(frozen=True)
class ResearchBudgetConfig:
    version: str = "0.1"
    calibration_label: str = "uncalibrated"
    theme_research_slots: int = 8
    full_decision_slots: int = 3
    minimum_independent_sources: int = 1
    confidence_floor: float = 0.45
    full_priority_gate: float = 0.65
    full_novelty_gate: float = 0.35


def load_research_budget_config(path: str | Path) -> ResearchBudgetConfig:
    payload = dict(yaml.safe_load(Path(path).read_text()))
    payload["calibration_label"] = "uncalibrated"
    return ResearchBudgetConfig(**payload)


class ResearchBudgetAllocator:
    def allocate(
        self,
        scan_results: Sequence[ThemeScanResult],
        registry_state: Mapping[str, ThemeDefinition],
        config: ResearchBudgetConfig,
        *,
        cycle_as_of: str,
    ) -> list[ResearchAllocation]:
        if config.theme_research_slots < 0 or config.full_decision_slots < 0:
            raise ValueError("research slot counts must be non-negative")

        cycle_dt = _parse_utc(cycle_as_of)
        state: dict[str, dict[str, object]] = {}

        for scan in scan_results:
            if _parse_utc(scan.as_of) > cycle_dt:
                raise ValueError("future-dated scan result")
            reasons: list[str] = []
            definition = registry_state.get(scan.theme_id)
            if definition is None:
                reasons.append("theme not registered")
            state[scan.theme_id] = {
                "scan": scan,
                "definition": definition,
                "tier": ResearchTier.SCAN_ONLY,
                "reasons": reasons,
            }

        theme_used = 0
        full_used = 0

        forced = [
            item
            for item in state.values()
            if item["definition"] is not None and item["scan"].forced_review
        ]
        forced.sort(
            key=lambda item: (
                -item["scan"].forced_review_severity,
                -item["scan"].research_priority,
                -item["scan"].evidence_confidence,
                item["scan"].theme_id,
            )
        )

        for item in forced:
            if theme_used >= config.theme_research_slots or full_used >= config.full_decision_slots:
                item["reasons"].append("forced review capacity exhausted")
                continue
            item["tier"] = ResearchTier.FULL_DECISION_RESEARCH
            item["reasons"].extend(item["scan"].forced_review_reasons)
            theme_used += 1
            full_used += 1

        ordinary: list[dict[str, object]] = []
        for item in state.values():
            scan = item["scan"]
            definition = item["definition"]
            if item["tier"] is ResearchTier.FULL_DECISION_RESEARCH:
                continue
            if scan.forced_review:
                continue
            if definition is None:
                continue
            if definition.lifecycle_state is not ThemeLifecycleState.STRENGTHENING:
                item["reasons"].append("theme lifecycle not strengthening")
                continue
            if scan.independent_support_count < config.minimum_independent_sources:
                item["reasons"].append("independent corroboration missing")
                continue
            if scan.independent_contradiction_count > 0:
                item["reasons"].append("independent contradiction unresolved")
                continue
            if scan.evidence_confidence < config.confidence_floor:
                item["reasons"].append("evidence confidence below floor")
                continue
            ordinary.append(item)

        ordinary.sort(
            key=lambda item: (
                -item["scan"].research_priority,
                -item["scan"].evidence_confidence,
                item["scan"].theme_id,
            )
        )

        for item in ordinary:
            scan = item["scan"]
            if theme_used >= config.theme_research_slots:
                item["reasons"].append("research capacity exhausted")
                continue
            if (
                full_used < config.full_decision_slots
                and scan.research_priority >= config.full_priority_gate
                and scan.novelty_score is not None
                and scan.novelty_score >= config.full_novelty_gate
            ):
                item["tier"] = ResearchTier.FULL_DECISION_RESEARCH
                item["reasons"].append("full research gates satisfied")
                theme_used += 1
                full_used += 1

        for item in ordinary:
            if item["tier"] is ResearchTier.FULL_DECISION_RESEARCH:
                continue
            if theme_used >= config.theme_research_slots:
                if "research capacity exhausted" not in item["reasons"]:
                    item["reasons"].append("research capacity exhausted")
                continue
            item["tier"] = ResearchTier.THEME_RESEARCH
            item["reasons"].append("theme research gates satisfied")
            theme_used += 1

        allocations = [
            ResearchAllocation(
                theme_id=item["scan"].theme_id,
                as_of=cycle_as_of,
                tier=item["tier"],
                priority=item["scan"].research_priority,
                forced_review=item["scan"].forced_review,
                allocation_reasons=tuple(item["reasons"]),
                source_scan_result_hash=canonical_hash(asdict(item["scan"])),
            )
            for item in state.values()
        ]
        tier_rank = {
            ResearchTier.FULL_DECISION_RESEARCH: 0,
            ResearchTier.THEME_RESEARCH: 1,
            ResearchTier.SCAN_ONLY: 2,
        }
        return sorted(
            allocations,
            key=lambda item: (
                tier_rank[item.tier],
                -int(item.forced_review),
                -item.priority,
                item.theme_id,
            ),
        )
```

Add a local `_parse_utc` helper in this module with the same normalization semantics as scanner.py. Do not import scanner.py's private helper.

Implementation rules:

1. Reject any scan result with `result.as_of > cycle_as_of`.
2. Start every result as `SCAN_ONLY`.
3. Unknown theme -> stay scan-only with `"theme not registered"`.
4. Only effective registry state `STRENGTHENING` is ordinary-promotion eligible.
5. Independent support below minimum -> scan-only with `"independent corroboration missing"`.
6. Confidence below floor -> scan-only with `"evidence confidence below floor"`.
7. Build forced candidates only from known themes with `forced_review=True`.
8. Sort forced candidates by:
   ```python
   (-forced_review_severity, -research_priority, -evidence_confidence, theme_id)
   ```
9. Admit forced candidates into FULL while both theme/full slots remain.
10. Ordinary full candidates are eligible if:
    - ordinary theme eligibility passes;
    - priority >= full_priority_gate;
    - novelty is not None and novelty >= full_novelty_gate.
11. Sort ordinary candidates by:
    ```python
    (-research_priority, -evidence_confidence, theme_id)
    ```
12. Admit ordinary full candidates until full slots or theme slots are exhausted.
13. Admit remaining ordinary theme-research candidates until theme slots are exhausted.
14. A FULL allocation increments both `theme_used` and `full_used` exactly once.
15. All unadmitted known themes remain SCAN_ONLY with a reason such as `"research capacity exhausted"` when otherwise eligible.
16. Return allocations sorted with non-scan tiers first using:
    ```python
    tier_rank = {
        ResearchTier.FULL_DECISION_RESEARCH: 0,
        ResearchTier.THEME_RESEARCH: 1,
        ResearchTier.SCAN_ONLY: 2,
    }
    key = (
        tier_rank[item.tier],
        -int(item.forced_review),
        -item.priority,
        item.theme_id,
    )
    ```
17. `source_scan_result_hash = canonical_hash(asdict(scan_result))`.
18. Never read or modify ThemeKey policy.

- [ ] **Step 4: Run allocator tests and verify GREEN**

Run:

```bash
pytest -q tests/test_research_budget.py
```

Expected: all allocator tests PASS.

- [ ] **Step 5: Run scanner + allocator together**

Run:

```bash
pytest -q tests/test_scanner.py tests/test_research_budget.py
```

Expected: PASS.

- [ ] **Step 6: Run the complete suite**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/decision_lab/research_budget.py tests/test_research_budget.py
git commit -m "feat: add bounded research budget allocator"
```

---

### Task 4: Versioned configuration, public API, README, and integration regression gates

**Files:**
- Create: `config/scanner/world_scanner_defaults.yaml`
- Create: `config/policies/research_budget_defaults.yaml`
- Modify: `src/decision_lab/__init__.py`
- Modify: `tests/test_scanner.py`
- Modify: `tests/test_research_budget.py`
- Modify: `README.md`

**Interfaces:**
- Consumes all Task 1-3 public types/loaders.
- Produces stable public imports and versioned public-safe config files.

- [ ] **Step 1: Write RED config/public API tests**

Append to `tests/test_scanner.py`:

```python
from pathlib import Path

from decision_lab.scanner import load_scanner_config

ROOT = Path(__file__).resolve().parents[1]


def test_world_scanner_default_config_matches_approved_uncalibrated_defaults():
    config = load_scanner_config(ROOT / "config/scanner/world_scanner_defaults.yaml")

    assert config.version == "0.1"
    assert config.calibration_label == "uncalibrated"
    assert config.stale_after_days == 5
    assert config.component_weights["discovery"] == 0.15
    assert config.component_weights["structural"] == 0.20
    assert config.hard_contradiction_ratio == 0.50


def test_scanner_interfaces_are_publicly_importable():
    import decision_lab

    assert decision_lab.ThemeScanObservation is not None
    assert decision_lab.ThemeScanResult is not None
    assert decision_lab.ScannerConfig is not None
    assert decision_lab.rank_themes is not None
```

Append to `tests/test_research_budget.py`:

```python
from pathlib import Path

from decision_lab.research_budget import load_research_budget_config

ROOT = Path(__file__).resolve().parents[1]


def test_research_budget_default_config_matches_approved_capacity_contract():
    config = load_research_budget_config(
        ROOT / "config/policies/research_budget_defaults.yaml"
    )

    assert config.version == "0.1"
    assert config.calibration_label == "uncalibrated"
    assert config.theme_research_slots == 8
    assert config.full_decision_slots == 3
    assert config.minimum_independent_sources == 1
    assert config.confidence_floor == 0.45
    assert config.full_priority_gate == 0.65
    assert config.full_novelty_gate == 0.35


def test_research_budget_interfaces_are_publicly_importable():
    import decision_lab

    assert decision_lab.ResearchTier is not None
    assert decision_lab.ResearchAllocation is not None
    assert decision_lab.ResearchBudgetConfig is not None
    assert decision_lab.ResearchBudgetAllocator is not None
```

- [ ] **Step 2: Run config/public tests and verify RED**

Run:

```bash
pytest -q tests/test_scanner.py tests/test_research_budget.py
```

Expected: failures because YAML configs and public exports are not yet present.

- [ ] **Step 3: Add exact versioned scanner config**

Create `config/scanner/world_scanner_defaults.yaml`:

```yaml
version: "0.1"
calibration_label: uncalibrated
stale_after_days: 5

source_weights:
  sec_filing: 1.00
  company_ir: 1.00
  official_macro: 1.00
  industry_primary: 0.95
  market_data: 0.90
  reputable_reporting: 0.75
  derived_feature: 0.60
  radar_model_output: 0.50

component_weights:
  discovery: 0.15
  structural: 0.20
  persistence: 0.15
  breadth: 0.10
  relative_strength: 0.10
  novelty: 0.15
  evidence_confidence: 0.15

contradiction_staleness_penalty: 0.25
strengthening_structure_gate: 0.60
strengthening_persistence_gate: 0.60
weakening_low_persistence_gate: 0.35
weakening_low_breadth_gate: 0.35
hard_contradiction_ratio: 0.50
dormant_no_support_cycles: 3
novelty_floor: 0.20
repeated_no_change_penalty_per_cycle: 0.10
repeated_no_change_penalty_cap: 0.30
```

- [ ] **Step 4: Add exact versioned budget config**

Create `config/policies/research_budget_defaults.yaml`:

```yaml
version: "0.1"
calibration_label: uncalibrated
theme_research_slots: 8
full_decision_slots: 3
minimum_independent_sources: 1
confidence_floor: 0.45
full_priority_gate: 0.65
full_novelty_gate: 0.35
```

- [ ] **Step 5: Export public interfaces**

Modify `src/decision_lab/__init__.py` to import/export exactly:

```python
from .research_budget import (
    ResearchAllocation,
    ResearchBudgetAllocator,
    ResearchBudgetConfig,
    ResearchTier,
    load_research_budget_config,
)
from .scanner import (
    ScannerConfig,
    SupportDirection,
    ThemeScanObservation,
    ThemeScanResult,
    load_scanner_config,
    rank_themes,
)
```

Add all ten names to `__all__`.

- [ ] **Step 6: Update README only after tests are green**

Replace the stale Market-wide architecture paragraph that says the current increment intentionally lacks a global scanner/second live theme.

The updated paragraph must state, in substance:

```text
DataCenter_Infra and Genomics_Bio are now normal theme packages. A deterministic World Scanner consumes cheap multi-source theme observations, keeps Radar/model evidence distinct from independent evidence, and produces lifecycle/priority recommendations. A capacity-limited Research Budget Allocator routes only eligible themes into theme research or full decision research. This layer allocates research attention only; ThemeKey, Tape, A-H routing, ledger immutability, and no-brokerage-execution invariants remain separate.
```

Do not claim the scanner automatically discovers themes from all listed securities; ticker-first clustering remains deferred.

- [ ] **Step 7: Run config/public tests and verify GREEN**

Run:

```bash
pytest -q tests/test_scanner.py tests/test_research_budget.py
```

Expected: PASS.

- [ ] **Step 8: Run full suite**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add config/scanner/world_scanner_defaults.yaml config/policies/research_budget_defaults.yaml src/decision_lab/__init__.py tests/test_scanner.py tests/test_research_budget.py README.md
git commit -m "config: publish scanner and research budget defaults"
```

---

### Task 5: Final safety audit, changed-files Ruff, and whole-branch review

**Files:**
- Verify: `src/decision_lab/scanner.py`
- Verify: `src/decision_lab/research_budget.py`
- Verify: `src/decision_lab/__init__.py`
- Verify: `tests/test_scanner.py`
- Verify: `tests/test_research_budget.py`
- Verify: `README.md`
- Review-only: `src/decision_lab/tape.py`
- Review-only: `src/decision_lab/playbooks.py`
- Review-only: `src/decision_lab/hierarchical.py`
- Review-only: `src/decision_lab/themes.py`
- Review-only: `src/decision_lab/ledger.py`

**Interfaces:**
- Consumes final branch from Tasks 1-4.
- Produces verification evidence; no new behavior.

- [ ] **Step 1: Run fresh full regression suite**

Run:

```bash
pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run changed-files Ruff**

Run:

```bash
python -m ruff check   src/decision_lab/scanner.py   src/decision_lab/research_budget.py   src/decision_lab/__init__.py   tests/test_scanner.py   tests/test_research_budget.py
```

Expected: exit 0.

- [ ] **Step 3: Audit forbidden semantic drift**

Run/read the equivalent of:

```bash
git diff main...HEAD --   src/decision_lab/tape.py   src/decision_lab/playbooks.py   src/decision_lab/hierarchical.py   src/decision_lab/themes.py   src/decision_lab/ledger.py
```

Expected: no changes.

Also verify:

```bash
grep -R "ledger/live" .github src scripts
```

Expected: no newly enabled write/schedule path.

Verify no scheduled workflow was added:

```bash
git diff --name-only main...HEAD -- .github/workflows
```

Expected: no Increment-3 workflow file.

- [ ] **Step 4: Review whole branch against the spec and Review Focus**

Review specifically:

- duplicate same-source evidence cannot inflate independent corroboration;
- timestamp normalization does not compare naive and aware datetimes directly;
- missing all-positive components cannot produce NaN promotion;
- forced reviews never exceed configured full/theme caps;
- FULL consumes exactly one theme slot;
- model-only evidence cannot ordinarily promote;
- unknown theme cannot enter expensive research;
- scanner never mutates registry state;
- allocator never touches ThemeKey;
- result/allocation hashes bind to exact inputs.

Any Critical/Important finding gets one TDD fix pass: write a reproducing RED test, make it GREEN, then rerun full suite and Ruff.

- [ ] **Step 5: Final exact-tree verification**

On the exact final head:

```bash
pytest -q
python -m ruff check   src/decision_lab/scanner.py   src/decision_lab/research_budget.py   src/decision_lab/__init__.py   tests/test_scanner.py   tests/test_research_budget.py
```

Record exact pytest pass count/time and Ruff result before claiming completion.

- [ ] **Step 6: Keep feature branch unmerged**

Do not merge to `main` during implementation. Present integration options only after final review and fresh verification are green.
