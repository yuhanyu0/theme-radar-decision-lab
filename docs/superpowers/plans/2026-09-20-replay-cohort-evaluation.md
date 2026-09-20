# Replay Cohort / Walk-forward Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform validated immutable replay archives into deterministic cycle-horizon transitions and descriptive cohort summaries grounded primarily in future independent-evidence evolution.

**Architecture:** Add one pure `replay_cohort.py` module. It validates archive/replay semantic consistency, derives independent-evidence state and routing intent, constructs source-theme × future-cycle transitions with explicit `PRESENT / NOT_PRESENT / RIGHT_CENSORED` semantics, then summarizes those transitions without price outcomes or a unified score. Existing replay, archive, scanner, budget, and trading-outcome modules remain unchanged.

**Tech Stack:** Python 3.11, dataclasses, Enum, collections, statistics, existing `canonical_hash`, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-20-replay-cohort-evaluation-design.md`

## Global Constraints

- The public evaluator is exactly `evaluate_replay_cohort(records, horizons=(1, 3, 5)) -> ReplayCohortResult`.
- Evaluation horizons count subsequent replay cycles, never calendar days.
- Future independent-evidence evolution is the primary outcome channel.
- Future lifecycle/priority/confidence/novelty/forced-review/tier are descriptive system transitions only.
- `NO_OBSERVATION`, `NOT_PRESENT`, and `RIGHT_CENSORED` are distinct and must never be collapsed.
- Absence of independent evidence must never be labeled contradiction resolution.
- `ResearchAllocation` records routing intent, not proof that downstream research executed.
- No price return, alpha, benchmark return, MAE, MFE, success, accuracy, reward, or unified performance score is added.
- Budget-config identity must not be inferred from `ReplayCycleResult`.
- The evaluator accepts already-loaded `ReplayArchiveRecord` objects and never scans archive directories or calls `read_replay_archive`.
- Empty cohorts and one-cycle cohorts are valid.
- Input record order and horizon order must not affect output.
- Existing `replay.py`, `replay_archive.py`, `scanner.py`, `research_budget.py`, `market_observation.py`, `outcomes.py`, theme/universe/ledger/Tape/playbook semantics must not change.
- Branch stays unmerged until exact-final-tree pytest, changed-files Ruff, and whole-branch review are green.

## Review Focus

1. **Hash-valid but semantically inconsistent archives:** top-level batch/scan/allocation/theme-record coverage, per-theme equality, allocation source-scan hash, cycle timestamps, and single scanner-config hash must be checked before longitudinal analysis.
2. **Missingness leakage:** future `NOT_PRESENT`, future `PRESENT + NO_OBSERVATION`, and `RIGHT_CENSORED` must keep all unavailable system fields/deltas as `None` rather than zero/SCAN_ONLY/dormant.
3. **Independent-evidence comparability:** model-only source/future states and loss of independent coverage must make contradiction/evidence-class transitions `UNASSESSED`/None rather than resolution or unchanged.
4. **Parallel/duplicate cycles:** duplicate archive records must fail before cycle analysis; distinct archives normalizing to the same UTC cycle instant must fail as ambiguous rather than being tie-broken.
5. **Summary denominator integrity:** every source row must land in complete contradiction/tier/forced-review/scanner-config partitions, with right-censoring and NOT_PRESENT retained in denominators and means using only non-None deltas.

---

## File map

- Create `src/decision_lab/replay_cohort.py`
  - cohort enums/dataclasses/constants;
  - archive/replay semantic validation;
  - UTC cycle/horizon normalization;
  - independent-evidence state;
  - routing intent;
  - transition derivation;
  - descriptive summaries;
  - input/result hashing.
- Create `tests/test_replay_cohort.py`
  - pure validation tests;
  - evidence/routing tests;
  - missingness/right-censor tests;
  - three-cycle end-to-end replay/archive cohort fixture;
  - summary/hash/determinism tests.
- Modify `src/decision_lab/__init__.py`
  - export only Increment-7 public symbols.
- Do not modify:
  - `src/decision_lab/replay.py`
  - `src/decision_lab/replay_archive.py`
  - `src/decision_lab/scanner.py`
  - `src/decision_lab/research_budget.py`
  - `src/decision_lab/market_observation.py`
  - `src/decision_lab/outcomes.py`
  - `src/decision_lab/themes.py`
  - `src/decision_lab/universe.py`
  - `src/decision_lab/ledger.py`
  - `src/decision_lab/tape.py`
  - `src/decision_lab/playbooks.py`

---

### Task 1: Cohort public types, archive/cycle/horizon validation, and replay semantic consistency

**Files:**
- Create: `src/decision_lab/replay_cohort.py`
- Create: `tests/test_replay_cohort.py`

**Interfaces:**
- Consumes:
  - `ReplayArchiveRecord`
  - `build_replay_archive_record`
  - `ReplayCycleResult`
  - `ReplayThemeRecord`
  - `ReplayStatus`
  - `ResearchTier`
  - `canonical_hash`
- Produces all public enums/dataclasses plus a minimally working `evaluate_replay_cohort` for empty input.
- Private helpers established here:
  - `_parse_cycle_utc(value: str) -> datetime`
  - `_normalize_horizons(values: Sequence[int]) -> tuple[int, ...]`
  - `_validate_archive_record(record: ReplayArchiveRecord) -> None`
  - `_validate_replay_semantics(result: ReplayCycleResult) -> None`
  - `_normalize_records(records) -> tuple[ReplayArchiveRecord, ...]`

- [ ] **Step 1: Write RED tests for public types, empty cohort, horizon validation, deterministic record ordering, duplicate archives, and ambiguous cycles**

Create `tests/test_replay_cohort.py`:

```python
from dataclasses import asdict, replace

import pytest

from decision_lab.ledger import canonical_hash
from decision_lab.replay import ReplayCycleInput, ReplayStatus, run_replay_cycle
from decision_lab.replay_archive import build_replay_archive_record
from decision_lab.replay_cohort import (
    ContradictionTransition,
    EvidenceClass,
    FuturePresence,
    IndependentEvidenceState,
    ReplayCohortResult,
    ReplayCohortSummary,
    ReplayCohortTransition,
    RoutingIntent,
    TierTransition,
    evaluate_replay_cohort,
)
from decision_lab.research_budget import ResearchBudgetConfig, ResearchTier
from decision_lab.scanner import (
    ScannerConfig,
    SupportDirection,
    ThemeScanObservation,
)


def _radar(theme="Rates", *, as_of="2026-09-19"):
    return ThemeScanObservation(
        theme_id=theme,
        as_of=as_of,
        source_type="radar_model_output",
        source_ref=f"radar:{theme}:{as_of}",
        discovery_signal=0.8,
        novelty_signal=0.6,
        support_direction=SupportDirection.SUPPORTING,
        evidence_refs=(f"radar:{theme}",),
        is_independent=False,
        observed_or_inferred="inferred",
    )


def _archive(
    *,
    cycle_as_of="2026-09-19",
    observations=None,
):
    observations = (
        (_radar(as_of=cycle_as_of),)
        if observations is None
        else tuple(observations)
    )
    result = run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of=cycle_as_of,
            themes=(),
            external_observations=observations,
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
    return build_replay_archive_record(result)


def test_empty_cohort_is_valid_and_deterministic():
    first = evaluate_replay_cohort((), horizons=(5, 1, 3))
    second = evaluate_replay_cohort((), horizons=(1, 3, 5))

    assert first == second
    assert first.schema_version == "0.1"
    assert (
        first.evaluation_scope
        == "evidence_evolution_and_descriptive_system_transition"
    )
    assert first.horizons == (1, 3, 5)
    assert first.cycles == ()
    assert first.archive_record_hashes == ()
    assert first.transitions == ()
    assert first.summaries == ()
    assert len(first.input_hash) == 64
    assert len(first.result_hash) == 64
    assert "directional price prediction" in first.limitations[-1]


@pytest.mark.parametrize("bad", [0, -1, 1.0, "1", True, False])
def test_invalid_horizon_is_rejected(bad):
    with pytest.raises(
        ValueError,
        match="cohort horizons must be positive integers",
    ):
        evaluate_replay_cohort((), horizons=(bad,))


def test_duplicate_horizon_is_rejected():
    with pytest.raises(ValueError, match="duplicate cohort horizon"):
        evaluate_replay_cohort((), horizons=(1, 3, 1))


def test_record_input_order_is_irrelevant():
    first_record = _archive(cycle_as_of="2026-09-19")
    second_record = _archive(cycle_as_of="2026-09-20")

    first = evaluate_replay_cohort(
        (first_record, second_record),
        horizons=(1,),
    )
    second = evaluate_replay_cohort(
        (second_record, first_record),
        horizons=(1,),
    )

    assert first == second
    assert first.cycles == ("2026-09-19", "2026-09-20")


def test_duplicate_archive_record_is_rejected():
    record = _archive()

    with pytest.raises(
        ValueError,
        match="duplicate replay archive record",
    ):
        evaluate_replay_cohort((record, record), horizons=(1,))


def test_distinct_archives_at_same_normalized_cycle_are_ambiguous():
    date_record = _archive(
        cycle_as_of="2026-09-19",
        observations=(_radar("Rates", as_of="2026-09-19"),),
    )
    timestamp_record = _archive(
        cycle_as_of="2026-09-19T23:59:59.999999+00:00",
        observations=(
            _radar(
                "OtherTheme",
                as_of="2026-09-19T23:59:59.999999+00:00",
            ),
        ),
    )

    with pytest.raises(ValueError, match="ambiguous cohort cycle"):
        evaluate_replay_cohort(
            (date_record, timestamp_record),
            horizons=(1,),
        )
```

- [ ] **Step 2: Add RED helpers for constructing hash-valid but semantically inconsistent replay archives**

Append:

```python
def _rehash_result(result):
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
    return replace(result, result_hash=canonical_hash(payload))


def _archive_from_semantically_modified_result(result):
    return build_replay_archive_record(_rehash_result(result))
```

Add consistency tests:

```python
def test_hash_valid_duplicate_theme_records_are_rejected():
    record = _archive()
    result = record.replay_result
    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            theme_records=(
                result.theme_records[0],
                result.theme_records[0],
            ),
        )
    )

    with pytest.raises(ValueError, match="inconsistent replay theme record"):
        evaluate_replay_cohort((bad,), horizons=(1,))


def test_hash_valid_routed_record_must_match_top_level_scan():
    record = _archive()
    result = record.replay_result
    theme_record = result.theme_records[0]
    changed_scan = replace(
        theme_record.scan_result,
        research_priority=0.123,
    )
    bad_record = replace(
        theme_record,
        scan_result=changed_scan,
    )
    bad = _archive_from_semantically_modified_result(
        replace(result, theme_records=(bad_record,))
    )

    with pytest.raises(ValueError, match="inconsistent replay theme record"):
        evaluate_replay_cohort((bad,), horizons=(1,))


def test_hash_valid_allocation_scan_hash_mismatch_is_rejected():
    record = _archive()
    result = record.replay_result
    allocation = replace(
        result.allocations[0],
        source_scan_result_hash="0" * 64,
    )
    theme_record = replace(
        result.theme_records[0],
        allocation=allocation,
    )
    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            allocations=(allocation,),
            theme_records=(theme_record,),
        )
    )

    with pytest.raises(
        ValueError,
        match="allocation scan-result hash mismatch",
    ):
        evaluate_replay_cohort((bad,), horizons=(1,))


def test_hash_valid_observation_without_theme_record_is_rejected():
    record = _archive()
    result = record.replay_result
    extra = _radar("Ghost", as_of=result.cycle_as_of)
    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            combined_observations=(
                *result.combined_observations,
                extra,
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match="observation theme missing from replay records",
    ):
        evaluate_replay_cohort((bad,), horizons=(1,))
```

- [ ] **Step 3: Run Task-1 tests and verify RED**

Run:

```bash
pytest -q tests/test_replay_cohort.py
```

Expected: collection error because `decision_lab.replay_cohort` does not exist.

- [ ] **Step 4: Implement public enums/dataclasses/constants**

Create `src/decision_lab/replay_cohort.py` with:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from statistics import mean

from .ledger import canonical_hash
from .replay import ReplayCycleResult, ReplayStatus, ReplayThemeRecord
from .replay_archive import ReplayArchiveRecord, build_replay_archive_record
from .research_budget import ResearchAllocation, ResearchTier
from .scanner import SupportDirection, ThemeScanObservation, ThemeScanResult

SCHEMA_VERSION = "0.1"
EVALUATION_SCOPE = (
    "evidence_evolution_and_descriptive_system_transition"
)
LIMITATIONS = (
    "future system state is descriptive, not independent ground truth",
    "budget config identity is not recoverable from ReplayCycleResult alone",
    "allocation tier records routing intent, not proof downstream research executed",
    "research allocation is not evaluated as a directional price prediction",
)


class EvidenceClass(str, Enum):
    NO_INDEPENDENT = "NO_INDEPENDENT"
    SUPPORT_ONLY = "SUPPORT_ONLY"
    CONTRADICTION_PRESENT = "CONTRADICTION_PRESENT"
    NEUTRAL_ONLY = "NEUTRAL_ONLY"
    MIXED = "MIXED"


class FuturePresence(str, Enum):
    PRESENT = "PRESENT"
    NOT_PRESENT = "NOT_PRESENT"
    RIGHT_CENSORED = "RIGHT_CENSORED"


class RoutingIntent(str, Enum):
    NO_OBSERVATION = "NO_OBSERVATION"
    SCAN_ONLY = "SCAN_ONLY"
    ORDINARY_THEME_RESEARCH = "ORDINARY_THEME_RESEARCH"
    ORDINARY_FULL_RESEARCH = "ORDINARY_FULL_RESEARCH"
    FORCED_FULL_REVIEW = "FORCED_FULL_REVIEW"
    FORCED_REVIEW_CAPACITY_MISSED = "FORCED_REVIEW_CAPACITY_MISSED"


class ContradictionTransition(str, Enum):
    ABSENT = "ABSENT"
    EMERGED = "EMERGED"
    PERSISTED = "PERSISTED"
    RESOLVED = "RESOLVED"
    UNASSESSED = "UNASSESSED"


class TierTransition(str, Enum):
    SAME = "SAME"
    ESCALATED = "ESCALATED"
    DEESCALATED = "DEESCALATED"
    UNASSESSED = "UNASSESSED"


@dataclass(frozen=True)
class IndependentEvidenceState:
    evidence_class: EvidenceClass
    independent_source_count: int
    supporting_source_count: int
    contradicting_source_count: int
    neutral_source_count: int
    supporting_source_refs: tuple[str, ...]
    contradicting_source_refs: tuple[str, ...]
    neutral_source_refs: tuple[str, ...]


@dataclass(frozen=True)
class ReplayCohortTransition:
    source_cycle_index: int
    future_cycle_index: int | None
    source_cycle_as_of: str
    future_cycle_as_of: str | None
    horizon_cycles: int
    source_archive_record_hash: str
    future_archive_record_hash: str | None
    theme_id: str
    routing_intent: RoutingIntent
    source_registered: bool
    future_presence: FuturePresence
    future_registered: bool | None
    source_evidence_state: IndependentEvidenceState
    future_evidence_state: IndependentEvidenceState | None
    support_delta: int | None
    contradiction_delta: int | None
    contradiction_transition: ContradictionTransition
    evidence_class_changed: bool | None
    source_replay_status: ReplayStatus
    future_replay_status: ReplayStatus | None
    source_scanner_config_hash: str | None
    future_scanner_config_hash: str | None
    scanner_config_changed: bool | None
    source_priority: float | None
    future_priority: float | None
    priority_delta: float | None
    source_confidence: float | None
    future_confidence: float | None
    confidence_delta: float | None
    source_novelty: float | None
    future_novelty: float | None
    novelty_delta: float | None
    source_lifecycle: str | None
    future_lifecycle: str | None
    source_forced_review: bool | None
    future_forced_review: bool | None
    source_tier: ResearchTier | None
    future_tier: ResearchTier | None
    tier_transition: TierTransition


@dataclass(frozen=True)
class ReplayCohortSummary:
    routing_intent: RoutingIntent
    horizon_cycles: int
    source_n: int
    future_cycle_available_n: int
    right_censored_n: int
    future_present_n: int
    future_not_present_n: int
    future_independent_evidence_n: int
    contradiction_unassessed_n: int
    contradiction_absent_n: int
    contradiction_emerged_n: int
    contradiction_persisted_n: int
    contradiction_resolved_n: int
    source_independent_evidence_n: int
    evidence_class_comparable_n: int
    evidence_class_changed_n: int
    tier_unassessed_n: int
    tier_same_n: int
    tier_escalated_n: int
    tier_deescalated_n: int
    forced_review_unassessed_n: int
    forced_review_inactive_n: int
    forced_review_emerged_n: int
    forced_review_persisted_n: int
    forced_review_resolved_n: int
    scanner_config_unassessed_n: int
    scanner_config_same_n: int
    scanner_config_changed_n: int
    priority_delta_n: int
    mean_priority_delta: float | None
    confidence_delta_n: int
    mean_confidence_delta: float | None
    novelty_delta_n: int
    mean_novelty_delta: float | None


@dataclass(frozen=True)
class ReplayCohortResult:
    schema_version: str
    evaluation_scope: str
    horizons: tuple[int, ...]
    cycles: tuple[str, ...]
    archive_record_hashes: tuple[str, ...]
    transitions: tuple[ReplayCohortTransition, ...]
    summaries: tuple[ReplayCohortSummary, ...]
    limitations: tuple[str, ...]
    input_hash: str
    result_hash: str
```

- [ ] **Step 5: Implement cycle/horizon/archive validation**

Add:

```python
def _parse_cycle_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    if "T" not in value and " " not in value:
        return dt.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )
    return dt


def _normalize_horizons(
    values: Sequence[int],
) -> tuple[int, ...]:
    normalized = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(
                "cohort horizons must be positive integers"
            )
        normalized.append(value)
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate cohort horizon")
    return tuple(sorted(normalized))


def _validate_archive_record(record: ReplayArchiveRecord) -> None:
    rebuilt = build_replay_archive_record(record.replay_result)
    if rebuilt != record:
        raise ValueError("invalid replay archive record")
```

- [ ] **Step 6: Implement replay semantic consistency validation**

Add:

```python
def _unique_by_theme(items, *, label: str):
    output = {}
    for item in items:
        if item.theme_id in output:
            raise ValueError("inconsistent replay theme record")
        output[item.theme_id] = item
    return output


def _validate_replay_semantics(result: ReplayCycleResult) -> None:
    batches = _unique_by_theme(
        result.market_batches,
        label="market batch",
    )
    scans = _unique_by_theme(
        result.scan_results,
        label="scan result",
    )
    allocations = _unique_by_theme(
        result.allocations,
        label="allocation",
    )
    records = _unique_by_theme(
        result.theme_records,
        label="theme record",
    )

    routed_ids = {
        item.theme_id
        for item in result.theme_records
        if item.replay_status is ReplayStatus.ROUTED
    }
    registered_ids = {
        item.theme_id
        for item in result.theme_records
        if item.registered
    }

    if set(scans) != routed_ids or set(allocations) != routed_ids:
        raise ValueError("inconsistent replay theme record")
    if set(batches) != registered_ids:
        raise ValueError("inconsistent replay theme record")

    scanner_hashes = {
        item.config_hash for item in result.scan_results
    }
    if len(scanner_hashes) > 1:
        raise ValueError(
            "multiple scanner config hashes in replay cycle"
        )

    for batch in result.market_batches:
        if batch.cycle_as_of != result.cycle_as_of:
            raise ValueError("inconsistent replay theme record")

    for scan in result.scan_results:
        if scan.as_of != result.cycle_as_of:
            raise ValueError("inconsistent replay theme record")

    for allocation in result.allocations:
        if allocation.as_of != result.cycle_as_of:
            raise ValueError("inconsistent replay theme record")

    for item in result.theme_records:
        if item.replay_status is ReplayStatus.NO_OBSERVATION:
            if (
                not item.registered
                or item.scan_result is not None
                or item.allocation is not None
            ):
                raise ValueError("inconsistent replay theme record")
        elif item.replay_status is ReplayStatus.ROUTED:
            if item.scan_result is None or item.allocation is None:
                raise ValueError("inconsistent replay theme record")
            if scans[item.theme_id] != item.scan_result:
                raise ValueError("inconsistent replay theme record")
            if allocations[item.theme_id] != item.allocation:
                raise ValueError("inconsistent replay theme record")
            expected_scan_hash = canonical_hash(
                asdict(item.scan_result)
            )
            if (
                item.allocation.source_scan_result_hash
                != expected_scan_hash
            ):
                raise ValueError(
                    "allocation scan-result hash mismatch"
                )
        else:
            raise ValueError("inconsistent replay theme record")

        if item.registered:
            if item.market_batch is None:
                raise ValueError("inconsistent replay theme record")
            if batches[item.theme_id] != item.market_batch:
                raise ValueError("inconsistent replay theme record")
        elif item.market_batch is not None:
            raise ValueError("inconsistent replay theme record")

    for observation in result.combined_observations:
        if observation.theme_id not in records:
            raise ValueError(
                "observation theme missing from replay records"
            )
```

- [ ] **Step 7: Implement record normalization and empty result hashing**

Add:

```python
def _normalize_records(
    records: Sequence[ReplayArchiveRecord],
) -> tuple[ReplayArchiveRecord, ...]:
    seen_hashes = set()
    rows = []
    for record in records:
        if record.archive_record_hash in seen_hashes:
            raise ValueError("duplicate replay archive record")
        seen_hashes.add(record.archive_record_hash)
        _validate_archive_record(record)
        _validate_replay_semantics(record.replay_result)
        rows.append((_parse_cycle_utc(record.cycle_as_of), record))

    rows.sort(key=lambda pair: pair[0])
    for left, right in zip(rows, rows[1:], strict=False):
        if left[0] == right[0]:
            raise ValueError("ambiguous cohort cycle")

    return tuple(record for _, record in rows)


def _cohort_input_hash(
    records: tuple[ReplayArchiveRecord, ...],
    horizons: tuple[int, ...],
) -> str:
    return canonical_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "evaluation_scope": EVALUATION_SCOPE,
            "horizons": list(horizons),
            "archive_record_hashes": [
                item.archive_record_hash for item in records
            ],
        }
    )


def _cohort_result_hash(
    *,
    horizons,
    records,
    transitions,
    summaries,
    input_hash,
) -> str:
    return canonical_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "evaluation_scope": EVALUATION_SCOPE,
            "horizons": list(horizons),
            "cycles": [
                item.cycle_as_of for item in records
            ],
            "archive_record_hashes": [
                item.archive_record_hash for item in records
            ],
            "transitions": [asdict(x) for x in transitions],
            "summaries": [asdict(x) for x in summaries],
            "limitations": list(LIMITATIONS),
            "input_hash": input_hash,
        }
    )


def evaluate_replay_cohort(
    records: Sequence[ReplayArchiveRecord],
    horizons: Sequence[int] = (1, 3, 5),
) -> ReplayCohortResult:
    normalized_horizons = _normalize_horizons(horizons)
    normalized_records = _normalize_records(records)
    input_hash = _cohort_input_hash(
        normalized_records,
        normalized_horizons,
    )
    result_hash = _cohort_result_hash(
        horizons=normalized_horizons,
        records=normalized_records,
        transitions=(),
        summaries=(),
        input_hash=input_hash,
    )
    return ReplayCohortResult(
        schema_version=SCHEMA_VERSION,
        evaluation_scope=EVALUATION_SCOPE,
        horizons=normalized_horizons,
        cycles=tuple(
            item.cycle_as_of for item in normalized_records
        ),
        archive_record_hashes=tuple(
            item.archive_record_hash for item in normalized_records
        ),
        transitions=(),
        summaries=(),
        limitations=LIMITATIONS,
        input_hash=input_hash,
        result_hash=result_hash,
    )
```

Task 2 will add non-empty transition semantics.

- [ ] **Step 8: Run Task-1 tests and full regression**

Run:

```bash
pytest -q tests/test_replay_cohort.py
pytest -q
```

Expected: PASS for Task-1 tests and all existing tests.

- [ ] **Step 9: Commit**

```bash
git add src/decision_lab/replay_cohort.py tests/test_replay_cohort.py
git commit -m "feat: add replay cohort validation boundary"
```

---

### Task 2: Independent-evidence state and routing-intent derivation

**Files:**
- Modify: `src/decision_lab/replay_cohort.py`
- Modify: `tests/test_replay_cohort.py`

**Interfaces:**
- Produces private:
  - `_independent_evidence_state(result, theme_id)`
  - `_routing_intent(theme_record)`
  - `_theme_system_state(theme_record)`
- Later transition code consumes these exact helpers.

- [ ] **Step 1: Add RED evidence-state tests**

Append a helper that generates observations directly:

```python
def _independent(
    theme,
    source_ref,
    direction,
    *,
    as_of="2026-09-19",
):
    return ThemeScanObservation(
        theme_id=theme,
        as_of=as_of,
        source_type="derived_feature",
        source_ref=source_ref,
        discovery_signal=0.9,
        structure_signal=0.9,
        persistence_signal=0.9,
        breadth_signal=0.9,
        relative_strength_signal=0.9,
        novelty_signal=0.9,
        support_direction=direction,
        evidence_refs=(source_ref,),
        is_independent=True,
        observed_or_inferred="inferred",
    )
```

Import private helpers for focused unit tests:

```python
from decision_lab.replay_cohort import (
    _independent_evidence_state,
    _routing_intent,
)
```

Add:

```python
@pytest.mark.parametrize(
    ("observations", "expected_class", "counts"),
    [
        ((), EvidenceClass.NO_INDEPENDENT, (0, 0, 0, 0)),
        (
            (_independent("T", "s1", SupportDirection.SUPPORTING),),
            EvidenceClass.SUPPORT_ONLY,
            (1, 1, 0, 0),
        ),
        (
            (_independent("T", "s1", SupportDirection.CONTRADICTING),),
            EvidenceClass.CONTRADICTION_PRESENT,
            (1, 0, 1, 0),
        ),
        (
            (_independent("T", "s1", SupportDirection.NEUTRAL),),
            EvidenceClass.NEUTRAL_ONLY,
            (1, 0, 0, 1),
        ),
        (
            (
                _independent("T", "a", SupportDirection.SUPPORTING),
                _independent("T", "b", SupportDirection.CONTRADICTING),
            ),
            EvidenceClass.MIXED,
            (2, 1, 1, 0),
        ),
    ],
)
def test_independent_evidence_classification(
    observations,
    expected_class,
    counts,
):
    record = _archive(
        observations=(
            *observations,
            _radar("T"),
        )
    )
    state = _independent_evidence_state(
        record.replay_result,
        "T",
    )

    assert state.evidence_class is expected_class
    assert (
        state.independent_source_count,
        state.supporting_source_count,
        state.contradicting_source_count,
        state.neutral_source_count,
    ) == counts


def test_same_independent_source_counts_once_with_contradiction_precedence():
    observations = (
        _independent("T", "same", SupportDirection.SUPPORTING),
        _independent("T", "same", SupportDirection.CONTRADICTING),
    )
    record = _archive(observations=observations)

    state = _independent_evidence_state(
        record.replay_result,
        "T",
    )

    assert state.independent_source_count == 1
    assert state.supporting_source_count == 0
    assert state.contradicting_source_count == 1
    assert state.contradicting_source_refs == ("same",)


def test_conflicting_source_metadata_is_rejected():
    first = _independent("T", "same", SupportDirection.SUPPORTING)
    second = replace(
        first,
        source_type="industry_primary",
    )
    record = _archive(observations=(first, second))

    with pytest.raises(
        ValueError,
        match="conflicting cohort source metadata",
    ):
        _independent_evidence_state(
            record.replay_result,
            "T",
        )
```

- [ ] **Step 2: Add RED registered-theme/routing-intent fixtures**

Add imports:

```python
from decision_lab.market_observation import (
    MarketBar,
    MarketObservationConfig,
    MarketObservationMode,
    MarketObservationSpec,
)
from decision_lab.replay import ThemeReplayInput
from decision_lab.themes import (
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemeLifecycleState,
    ThemePackage,
)
from decision_lab.universe import Candidate, ThemeLayer, ThemeUniverse
```

Add:

```python
def _package(theme):
    universe = ThemeUniverse(
        theme=theme,
        version="u1",
        generated_at="2026-09-19T00:00:00Z",
    )
    universe.add_layer(ThemeLayer("layer"))
    universe.add_candidate(
        Candidate(
            ticker=f"{theme[:3].upper()}1",
            theme=theme,
            layer="layer",
            effective_from="2026-01-01",
        )
    )
    return ThemePackage(
        definition=ThemeDefinition(
            theme_id=theme,
            display_name=theme,
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            effective_from="2026-01-01",
            version="1",
        ),
        universe=universe,
        theme_key_policy=ThemeKeyPolicy(),
        evidence_adapter="generic",
        version="p1",
        source_path="fixture",
    )


def _theme_input(theme, cycle_as_of):
    return ThemeReplayInput(
        package=_package(theme),
        market_spec=MarketObservationSpec(
            theme_id=theme,
            mode=MarketObservationMode.BASKET,
            benchmark="SPY",
            current_return_sessions=1,
            prior_return_sessions=1,
            min_basket_members=1,
            version="test",
        ),
        market_config=MarketObservationConfig(),
        bars=(
            MarketBar(
                symbol="SPY",
                session_date=cycle_as_of[:10],
                available_at=f"{cycle_as_of[:10]}T21:00:00+00:00",
                close=100,
            ),
        ),
        market_source_ref=f"fixture:{theme}:{cycle_as_of}",
    )


def _registered_archive(
    *,
    cycle_as_of="2026-09-19",
    themes=("FullTheme",),
    observations=(),
    budget_config=None,
):
    result = run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of=cycle_as_of,
            themes=tuple(
                _theme_input(theme, cycle_as_of)
                for theme in themes
            ),
            external_observations=tuple(observations),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=(
                budget_config or ResearchBudgetConfig()
            ),
        )
    )
    return build_replay_archive_record(result)
```

Add intent tests:

```python
def test_routing_intent_distinguishes_no_observation_and_ordinary_full():
    quiet = _registered_archive(
        themes=("Quiet",),
        observations=(),
    )
    assert (
        _routing_intent(quiet.replay_result.theme_records[0])
        is RoutingIntent.NO_OBSERVATION
    )

    full = _registered_archive(
        themes=("FullTheme",),
        observations=(
            _independent(
                "FullTheme",
                "independent:full",
                SupportDirection.SUPPORTING,
            ),
        ),
    )
    assert (
        _routing_intent(full.replay_result.theme_records[0])
        is RoutingIntent.ORDINARY_FULL_RESEARCH
    )


def test_routing_intent_distinguishes_forced_full_and_capacity_missed():
    contradiction = _independent(
        "RiskTheme",
        "independent:risk",
        SupportDirection.CONTRADICTING,
    )
    forced_full = _registered_archive(
        themes=("RiskTheme",),
        observations=(contradiction,),
    )
    assert (
        _routing_intent(forced_full.replay_result.theme_records[0])
        is RoutingIntent.FORCED_FULL_REVIEW
    )

    missed = _registered_archive(
        themes=("RiskTheme",),
        observations=(contradiction,),
        budget_config=replace(
            ResearchBudgetConfig(),
            full_decision_slots=0,
        ),
    )
    assert (
        _routing_intent(missed.replay_result.theme_records[0])
        is RoutingIntent.FORCED_REVIEW_CAPACITY_MISSED
    )
```

- [ ] **Step 3: Run Task-2 tests and verify RED**

Run:

```bash
pytest -q tests/test_replay_cohort.py
```

Expected: new tests fail because evidence/routing helpers do not exist.

- [ ] **Step 4: Implement independent evidence state**

Add:

```python
def _independent_evidence_state(
    result: ReplayCycleResult,
    theme_id: str,
) -> IndependentEvidenceState:
    grouped = {}
    for observation in result.combined_observations:
        if observation.theme_id != theme_id:
            continue
        grouped.setdefault(observation.source_ref, []).append(
            observation
        )

    support_refs = []
    contradiction_refs = []
    neutral_refs = []

    for source_ref, rows in grouped.items():
        metadata = {
            (row.source_type, row.is_independent)
            for row in rows
        }
        if len(metadata) != 1:
            raise ValueError(
                "conflicting cohort source metadata"
            )
        if not rows[0].is_independent:
            continue

        directions = {row.support_direction for row in rows}
        if SupportDirection.CONTRADICTING in directions:
            contradiction_refs.append(source_ref)
        elif SupportDirection.SUPPORTING in directions:
            support_refs.append(source_ref)
        else:
            neutral_refs.append(source_ref)

    support_refs.sort()
    contradiction_refs.sort()
    neutral_refs.sort()
    independent_count = (
        len(support_refs)
        + len(contradiction_refs)
        + len(neutral_refs)
    )

    if independent_count == 0:
        evidence_class = EvidenceClass.NO_INDEPENDENT
    elif support_refs and contradiction_refs:
        evidence_class = EvidenceClass.MIXED
    elif contradiction_refs:
        evidence_class = EvidenceClass.CONTRADICTION_PRESENT
    elif support_refs:
        evidence_class = EvidenceClass.SUPPORT_ONLY
    else:
        evidence_class = EvidenceClass.NEUTRAL_ONLY

    return IndependentEvidenceState(
        evidence_class=evidence_class,
        independent_source_count=independent_count,
        supporting_source_count=len(support_refs),
        contradicting_source_count=len(contradiction_refs),
        neutral_source_count=len(neutral_refs),
        supporting_source_refs=tuple(support_refs),
        contradicting_source_refs=tuple(contradiction_refs),
        neutral_source_refs=tuple(neutral_refs),
    )
```

- [ ] **Step 5: Implement routing-intent and forced-review consistency**

Add:

```python
def _routing_intent(
    item: ReplayThemeRecord,
) -> RoutingIntent:
    if item.replay_status is ReplayStatus.NO_OBSERVATION:
        return RoutingIntent.NO_OBSERVATION

    scan = item.scan_result
    allocation = item.allocation
    if scan is None or allocation is None:
        raise ValueError("inconsistent replay theme record")
    if scan.forced_review != allocation.forced_review:
        raise ValueError("forced-review flag mismatch")

    exhausted = (
        "forced review capacity exhausted"
        in allocation.allocation_reasons
    )

    if scan.forced_review:
        if (
            allocation.tier is ResearchTier.FULL_DECISION_RESEARCH
            and not exhausted
        ):
            return RoutingIntent.FORCED_FULL_REVIEW
        if (
            allocation.tier is ResearchTier.SCAN_ONLY
            and exhausted
        ):
            return RoutingIntent.FORCED_REVIEW_CAPACITY_MISSED
        raise ValueError(
            "unsupported forced-review allocation state"
        )

    if exhausted:
        raise ValueError(
            "unsupported forced-review allocation state"
        )
    if allocation.tier is ResearchTier.FULL_DECISION_RESEARCH:
        return RoutingIntent.ORDINARY_FULL_RESEARCH
    if allocation.tier is ResearchTier.THEME_RESEARCH:
        return RoutingIntent.ORDINARY_THEME_RESEARCH
    if allocation.tier is ResearchTier.SCAN_ONLY:
        return RoutingIntent.SCAN_ONLY
    raise ValueError("unsupported forced-review allocation state")
```

- [ ] **Step 6: Run Task-2 tests and full regression**

Run:

```bash
pytest -q tests/test_replay_cohort.py
pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/decision_lab/replay_cohort.py tests/test_replay_cohort.py
git commit -m "feat: derive cohort evidence and routing intent"
```

---

### Task 3: Horizon transition generation and explicit missingness

**Files:**
- Modify: `src/decision_lab/replay_cohort.py`
- Modify: `tests/test_replay_cohort.py`

**Interfaces:**
- Adds private:
  - `_contradiction_transition(source, future, presence)`
  - `_tier_transition(source, future)`
  - `_build_transition(...)`
  - `_build_transitions(...)`
- Extends `evaluate_replay_cohort` to emit deterministic transitions.

- [ ] **Step 1: Add RED one-cycle/right-censor and NOT_PRESENT/NO_OBSERVATION tests**

Add:

```python
def test_one_cycle_emits_right_censored_rows_for_every_horizon():
    source = _archive()
    result = evaluate_replay_cohort(
        (source,),
        horizons=(1, 3),
    )

    assert len(result.transitions) == 2
    assert {
        item.horizon_cycles for item in result.transitions
    } == {1, 3}
    for item in result.transitions:
        assert item.future_presence is FuturePresence.RIGHT_CENSORED
        assert item.future_cycle_index is None
        assert item.future_cycle_as_of is None
        assert item.future_evidence_state is None
        assert item.future_tier is None
        assert item.priority_delta is None
        assert (
            item.contradiction_transition
            is ContradictionTransition.UNASSESSED
        )
        assert item.tier_transition is TierTransition.UNASSESSED


def test_future_not_present_is_not_scan_only_or_no_observation():
    source = _archive(cycle_as_of="2026-09-19")
    future = _archive(
        cycle_as_of="2026-09-20",
        observations=(_radar("Other", as_of="2026-09-20"),),
    )

    result = evaluate_replay_cohort(
        (source, future),
        horizons=(1,),
    )
    row = next(
        item
        for item in result.transitions
        if item.source_cycle_index == 0
        and item.theme_id == "Rates"
    )

    assert row.future_presence is FuturePresence.NOT_PRESENT
    assert row.future_registered is None
    assert row.future_replay_status is None
    assert row.future_evidence_state is None
    assert row.future_tier is None
    assert row.future_priority is None
    assert row.priority_delta is None
    assert row.tier_transition is TierTransition.UNASSESSED
    assert (
        row.contradiction_transition
        is ContradictionTransition.UNASSESSED
    )


def test_future_present_no_observation_stays_distinct():
    source = _registered_archive(
        cycle_as_of="2026-09-19",
        themes=("Quiet",),
        observations=(),
    )
    future = _registered_archive(
        cycle_as_of="2026-09-20",
        themes=("Quiet",),
        observations=(),
    )

    result = evaluate_replay_cohort(
        (source, future),
        horizons=(1,),
    )
    row = result.transitions[0]

    assert row.future_presence is FuturePresence.PRESENT
    assert row.future_replay_status is ReplayStatus.NO_OBSERVATION
    assert row.future_tier is None
    assert (
        row.future_evidence_state.evidence_class
        is EvidenceClass.NO_INDEPENDENT
    )
```

- [ ] **Step 2: Add RED contradiction-comparability and tier-transition tests**

Add:

```python
def test_contradiction_requires_independent_evidence_on_both_sides():
    source = _archive(cycle_as_of="2026-09-19")
    future = _archive(
        cycle_as_of="2026-09-20",
        observations=(
            _independent(
                "Rates",
                "independent:risk",
                SupportDirection.CONTRADICTING,
                as_of="2026-09-20",
            ),
        ),
    )

    row = evaluate_replay_cohort(
        (source, future),
        horizons=(1,),
    ).transitions[0]

    assert (
        row.source_evidence_state.evidence_class
        is EvidenceClass.NO_INDEPENDENT
    )
    assert (
        row.contradiction_transition
        is ContradictionTransition.UNASSESSED
    )
    assert row.evidence_class_changed is None


@pytest.mark.parametrize(
    ("source_direction", "future_direction", "expected"),
    [
        (
            SupportDirection.SUPPORTING,
            SupportDirection.CONTRADICTING,
            ContradictionTransition.EMERGED,
        ),
        (
            SupportDirection.CONTRADICTING,
            SupportDirection.CONTRADICTING,
            ContradictionTransition.PERSISTED,
        ),
        (
            SupportDirection.CONTRADICTING,
            SupportDirection.SUPPORTING,
            ContradictionTransition.RESOLVED,
        ),
        (
            SupportDirection.SUPPORTING,
            SupportDirection.SUPPORTING,
            ContradictionTransition.ABSENT,
        ),
    ],
)
def test_contradiction_transition_with_comparable_independent_evidence(
    source_direction,
    future_direction,
    expected,
):
    source = _archive(
        cycle_as_of="2026-09-19",
        observations=(
            _independent(
                "T",
                "source",
                source_direction,
                as_of="2026-09-19",
            ),
        ),
    )
    future = _archive(
        cycle_as_of="2026-09-20",
        observations=(
            _independent(
                "T",
                "future",
                future_direction,
                as_of="2026-09-20",
            ),
        ),
    )

    row = evaluate_replay_cohort(
        (source, future),
        horizons=(1,),
    ).transitions[0]

    assert row.contradiction_transition is expected
    assert row.evidence_class_changed is (
        source_direction is not future_direction
    )
```

- [ ] **Step 3: Run Task-3 tests and verify RED**

Run:

```bash
pytest -q tests/test_replay_cohort.py
```

Expected: transition tests fail because evaluator still returns no transitions.

- [ ] **Step 4: Implement transition helpers**

Add:

```python
_TIER_RANK = {
    ResearchTier.SCAN_ONLY: 0,
    ResearchTier.THEME_RESEARCH: 1,
    ResearchTier.FULL_DECISION_RESEARCH: 2,
}


def _contradiction_transition(
    source: IndependentEvidenceState,
    future: IndependentEvidenceState | None,
    presence: FuturePresence,
) -> ContradictionTransition:
    if (
        presence is not FuturePresence.PRESENT
        or future is None
        or source.independent_source_count == 0
        or future.independent_source_count == 0
    ):
        return ContradictionTransition.UNASSESSED

    source_has = source.contradicting_source_count > 0
    future_has = future.contradicting_source_count > 0
    if not source_has and future_has:
        return ContradictionTransition.EMERGED
    if source_has and future_has:
        return ContradictionTransition.PERSISTED
    if source_has and not future_has:
        return ContradictionTransition.RESOLVED
    return ContradictionTransition.ABSENT


def _tier_transition(
    source: ResearchTier | None,
    future: ResearchTier | None,
) -> TierTransition:
    if source is None or future is None:
        return TierTransition.UNASSESSED
    if source is future:
        return TierTransition.SAME
    if _TIER_RANK[future] > _TIER_RANK[source]:
        return TierTransition.ESCALATED
    return TierTransition.DEESCALATED


def _delta(source, future):
    if source is None or future is None:
        return None
    return future - source
```

Add a simple state extractor:

```python
def _system_fields(item: ReplayThemeRecord):
    scan = item.scan_result
    allocation = item.allocation
    return {
        "scanner_config_hash": (
            None if scan is None else scan.config_hash
        ),
        "priority": (
            None if scan is None else scan.research_priority
        ),
        "confidence": (
            None if scan is None else scan.evidence_confidence
        ),
        "novelty": (
            None if scan is None else scan.novelty_score
        ),
        "lifecycle": (
            None if scan is None else scan.lifecycle_recommendation
        ),
        "forced_review": (
            None if scan is None else scan.forced_review
        ),
        "tier": (
            None if allocation is None else allocation.tier
        ),
    }
```

- [ ] **Step 5: Implement one transition builder**

Implement `_build_transition` so it:
1. derives source routing intent/evidence/system fields;
2. handles right-censor with all future fields None;
3. handles existing future cycle + absent theme as NOT_PRESENT;
4. handles PRESENT future theme, including future NO_OBSERVATION;
5. computes evidence counts/deltas only when future presence is PRESENT;
6. sets `evidence_class_changed` only when both evidence states have independent sources;
7. sets scanner_config_changed only when both hashes exist;
8. computes tier transition with `_tier_transition`.

Use exact field names from `ReplayCohortTransition`; do not add an intermediate public structure.

- [ ] **Step 6: Implement deterministic transition enumeration**

Add:

```python
def _build_transitions(
    records: tuple[ReplayArchiveRecord, ...],
    horizons: tuple[int, ...],
) -> tuple[ReplayCohortTransition, ...]:
    rows = []
    for source_index, source_record in enumerate(records):
        source_records = sorted(
            source_record.replay_result.theme_records,
            key=lambda item: item.theme_id,
        )
        for horizon in horizons:
            future_index = source_index + horizon
            future_record = (
                None
                if future_index >= len(records)
                else records[future_index]
            )
            for theme_record in source_records:
                rows.append(
                    _build_transition(
                        source_index=source_index,
                        source_record=source_record,
                        future_index=(
                            None
                            if future_record is None
                            else future_index
                        ),
                        future_record=future_record,
                        horizon=horizon,
                        source_theme_record=theme_record,
                    )
                )
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                item.source_cycle_index,
                item.horizon_cycles,
                item.theme_id,
            ),
        )
    )
```

Update `evaluate_replay_cohort` to use `_build_transitions` while summaries remain empty until Task 4.

- [ ] **Step 7: Run Task-3 tests and full regression**

Run:

```bash
pytest -q tests/test_replay_cohort.py
pytest -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/decision_lab/replay_cohort.py tests/test_replay_cohort.py
git commit -m "feat: build replay cohort transitions"
```

---

### Task 4: Cohort summaries, hashes, full three-cycle acceptance, and public exports

**Files:**
- Modify: `src/decision_lab/replay_cohort.py`
- Modify: `tests/test_replay_cohort.py`
- Modify: `src/decision_lab/__init__.py`

**Interfaces:**
- Finalizes:
  - `ReplayCohortSummary`
  - `ReplayCohortResult`
  - `evaluate_replay_cohort`
- Exports the 10 public Increment-7 names.

- [ ] **Step 1: Add RED full three-cycle acceptance fixture using real replay/archive composition**

Add a cycle factory:

```python
def _cycle_archive(cycle_as_of, *, dc_direction, bio_direction, include_rates):
    themes = (
        _theme_input("DataCenter_Infra", cycle_as_of),
        _theme_input("Genomics_Bio", cycle_as_of),
        _theme_input("Quiet", cycle_as_of),
    )
    observations = [
        _independent(
            "DataCenter_Infra",
            f"dc:{cycle_as_of}",
            dc_direction,
            as_of=cycle_as_of,
        ),
        _independent(
            "Genomics_Bio",
            f"bio:{cycle_as_of}",
            bio_direction,
            as_of=cycle_as_of,
        ),
    ]
    if include_rates:
        observations.append(
            _radar("Rates", as_of=cycle_as_of)
        )

    result = run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of=cycle_as_of,
            themes=themes,
            external_observations=tuple(observations),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
    return build_replay_archive_record(result)


def _three_cycle_cohort():
    c0 = _cycle_archive(
        "2026-09-19",
        dc_direction=SupportDirection.CONTRADICTING,
        bio_direction=SupportDirection.SUPPORTING,
        include_rates=True,
    )
    c1 = _cycle_archive(
        "2026-09-20",
        dc_direction=SupportDirection.CONTRADICTING,
        bio_direction=SupportDirection.SUPPORTING,
        include_rates=False,
    )
    c2 = _cycle_archive(
        "2026-09-21",
        dc_direction=SupportDirection.SUPPORTING,
        bio_direction=SupportDirection.CONTRADICTING,
        include_rates=True,
    )
    return c0, c1, c2
```

Add:

```python
def test_three_cycle_cohort_tracks_persist_resolve_emerge_and_absence():
    c0, c1, c2 = _three_cycle_cohort()
    result = evaluate_replay_cohort(
        (c2, c0, c1),
        horizons=(2, 1),
    )

    rows = {
        (
            item.source_cycle_index,
            item.horizon_cycles,
            item.theme_id,
        ): item
        for item in result.transitions
    }

    dc_h1 = rows[(0, 1, "DataCenter_Infra")]
    assert (
        dc_h1.routing_intent
        is RoutingIntent.FORCED_FULL_REVIEW
    )
    assert (
        dc_h1.contradiction_transition
        is ContradictionTransition.PERSISTED
    )

    dc_h2 = rows[(0, 2, "DataCenter_Infra")]
    assert (
        dc_h2.contradiction_transition
        is ContradictionTransition.RESOLVED
    )

    bio_h2 = rows[(0, 2, "Genomics_Bio")]
    assert (
        bio_h2.routing_intent
        is RoutingIntent.ORDINARY_FULL_RESEARCH
    )
    assert (
        bio_h2.contradiction_transition
        is ContradictionTransition.EMERGED
    )

    rates_h1 = rows[(0, 1, "Rates")]
    assert rates_h1.future_presence is FuturePresence.NOT_PRESENT
    assert rates_h1.future_tier is None

    rates_h2 = rows[(0, 2, "Rates")]
    assert rates_h2.future_presence is FuturePresence.PRESENT
    assert (
        rates_h2.future_evidence_state.evidence_class
        is EvidenceClass.NO_INDEPENDENT
    )

    quiet_h1 = rows[(0, 1, "Quiet")]
    assert quiet_h1.future_presence is FuturePresence.PRESENT
    assert quiet_h1.future_replay_status is ReplayStatus.NO_OBSERVATION

    assert any(
        item.future_presence is FuturePresence.RIGHT_CENSORED
        for item in result.transitions
        if item.source_cycle_index > 0
    )
```

- [ ] **Step 2: Add RED summary partition/mean tests**

Add:

```python
def test_summary_denominators_are_complete_partitions():
    result = evaluate_replay_cohort(
        _three_cycle_cohort(),
        horizons=(1, 2),
    )

    for summary in result.summaries:
        assert summary.source_n == (
            summary.future_cycle_available_n
            + summary.right_censored_n
        )
        assert summary.future_cycle_available_n == (
            summary.future_present_n
            + summary.future_not_present_n
        )
        assert summary.source_n == (
            summary.contradiction_unassessed_n
            + summary.contradiction_absent_n
            + summary.contradiction_emerged_n
            + summary.contradiction_persisted_n
            + summary.contradiction_resolved_n
        )
        assert summary.source_n == (
            summary.tier_unassessed_n
            + summary.tier_same_n
            + summary.tier_escalated_n
            + summary.tier_deescalated_n
        )
        assert summary.source_n == (
            summary.forced_review_unassessed_n
            + summary.forced_review_inactive_n
            + summary.forced_review_emerged_n
            + summary.forced_review_persisted_n
            + summary.forced_review_resolved_n
        )
        assert summary.source_n == (
            summary.scanner_config_unassessed_n
            + summary.scanner_config_same_n
            + summary.scanner_config_changed_n
        )
        assert (
            summary.evidence_class_changed_n
            <= summary.evidence_class_comparable_n
        )


def test_summary_mean_counts_match_non_none_transition_deltas():
    result = evaluate_replay_cohort(
        _three_cycle_cohort(),
        horizons=(1,),
    )

    for summary in result.summaries:
        rows = [
            item
            for item in result.transitions
            if item.routing_intent is summary.routing_intent
            and item.horizon_cycles == summary.horizon_cycles
        ]

        priority = [
            item.priority_delta
            for item in rows
            if item.priority_delta is not None
        ]
        assert summary.priority_delta_n == len(priority)
        assert summary.mean_priority_delta == (
            None
            if not priority
            else pytest.approx(sum(priority) / len(priority))
        )

        confidence = [
            item.confidence_delta
            for item in rows
            if item.confidence_delta is not None
        ]
        assert summary.confidence_delta_n == len(confidence)

        novelty = [
            item.novelty_delta
            for item in rows
            if item.novelty_delta is not None
        ]
        assert summary.novelty_delta_n == len(novelty)
```

- [ ] **Step 3: Add RED hash/order/public-export tests**

Add:

```python
def test_cohort_hashes_are_deterministic_and_bind_records_and_horizons():
    c0, c1, c2 = _three_cycle_cohort()

    first = evaluate_replay_cohort(
        (c0, c1, c2),
        horizons=(2, 1),
    )
    second = evaluate_replay_cohort(
        (c2, c0, c1),
        horizons=(1, 2),
    )

    assert second == first

    changed_horizon = evaluate_replay_cohort(
        (c0, c1, c2),
        horizons=(1,),
    )
    assert changed_horizon.input_hash != first.input_hash

    changed_record = evaluate_replay_cohort(
        (c0, c1),
        horizons=(1, 2),
    )
    assert changed_record.input_hash != first.input_hash


def test_result_hash_binds_complete_cohort_output():
    result = evaluate_replay_cohort(
        _three_cycle_cohort(),
        horizons=(1, 2),
    )
    payload = {
        "schema_version": result.schema_version,
        "evaluation_scope": result.evaluation_scope,
        "horizons": list(result.horizons),
        "cycles": list(result.cycles),
        "archive_record_hashes": list(result.archive_record_hashes),
        "transitions": [asdict(x) for x in result.transitions],
        "summaries": [asdict(x) for x in result.summaries],
        "limitations": list(result.limitations),
        "input_hash": result.input_hash,
    }
    assert result.result_hash == canonical_hash(payload)


def test_replay_cohort_interfaces_are_publicly_importable():
    import decision_lab

    for name in (
        "EvidenceClass",
        "FuturePresence",
        "RoutingIntent",
        "ContradictionTransition",
        "TierTransition",
        "IndependentEvidenceState",
        "ReplayCohortTransition",
        "ReplayCohortSummary",
        "ReplayCohortResult",
        "evaluate_replay_cohort",
    ):
        assert getattr(decision_lab, name) is not None
```

- [ ] **Step 4: Run Task-4 tests and verify RED**

Run:

```bash
pytest -q tests/test_replay_cohort.py
```

Expected: summary tests and public exports fail; transition tests from Task 3 remain green.

- [ ] **Step 5: Implement descriptive summary builder**

Add:

```python
def _mean_or_none(values):
    return None if not values else mean(values)


def _build_summary(
    routing_intent: RoutingIntent,
    horizon: int,
    rows: Sequence[ReplayCohortTransition],
) -> ReplayCohortSummary:
    contradiction_counts = {
        value: sum(
            item.contradiction_transition is value
            for item in rows
        )
        for value in ContradictionTransition
    }
    tier_counts = {
        value: sum(
            item.tier_transition is value
            for item in rows
        )
        for value in TierTransition
    }

    forced_unassessed = 0
    forced_inactive = 0
    forced_emerged = 0
    forced_persisted = 0
    forced_resolved = 0
    scanner_unassessed = 0
    scanner_same = 0
    scanner_changed = 0

    for item in rows:
        if (
            item.source_forced_review is None
            or item.future_forced_review is None
        ):
            forced_unassessed += 1
        elif not item.source_forced_review and not item.future_forced_review:
            forced_inactive += 1
        elif not item.source_forced_review and item.future_forced_review:
            forced_emerged += 1
        elif item.source_forced_review and item.future_forced_review:
            forced_persisted += 1
        else:
            forced_resolved += 1

        if item.scanner_config_changed is None:
            scanner_unassessed += 1
        elif item.scanner_config_changed:
            scanner_changed += 1
        else:
            scanner_same += 1

    priority = [
        item.priority_delta
        for item in rows
        if item.priority_delta is not None
    ]
    confidence = [
        item.confidence_delta
        for item in rows
        if item.confidence_delta is not None
    ]
    novelty = [
        item.novelty_delta
        for item in rows
        if item.novelty_delta is not None
    ]

    return ReplayCohortSummary(
        routing_intent=routing_intent,
        horizon_cycles=horizon,
        source_n=len(rows),
        future_cycle_available_n=sum(
            item.future_presence is not FuturePresence.RIGHT_CENSORED
            for item in rows
        ),
        right_censored_n=sum(
            item.future_presence is FuturePresence.RIGHT_CENSORED
            for item in rows
        ),
        future_present_n=sum(
            item.future_presence is FuturePresence.PRESENT
            for item in rows
        ),
        future_not_present_n=sum(
            item.future_presence is FuturePresence.NOT_PRESENT
            for item in rows
        ),
        future_independent_evidence_n=sum(
            item.future_evidence_state is not None
            and item.future_evidence_state.independent_source_count > 0
            for item in rows
        ),
        contradiction_unassessed_n=contradiction_counts[
            ContradictionTransition.UNASSESSED
        ],
        contradiction_absent_n=contradiction_counts[
            ContradictionTransition.ABSENT
        ],
        contradiction_emerged_n=contradiction_counts[
            ContradictionTransition.EMERGED
        ],
        contradiction_persisted_n=contradiction_counts[
            ContradictionTransition.PERSISTED
        ],
        contradiction_resolved_n=contradiction_counts[
            ContradictionTransition.RESOLVED
        ],
        source_independent_evidence_n=sum(
            item.source_evidence_state.independent_source_count > 0
            for item in rows
        ),
        evidence_class_comparable_n=sum(
            item.evidence_class_changed is not None
            for item in rows
        ),
        evidence_class_changed_n=sum(
            item.evidence_class_changed is True
            for item in rows
        ),
        tier_unassessed_n=tier_counts[TierTransition.UNASSESSED],
        tier_same_n=tier_counts[TierTransition.SAME],
        tier_escalated_n=tier_counts[TierTransition.ESCALATED],
        tier_deescalated_n=tier_counts[TierTransition.DEESCALATED],
        forced_review_unassessed_n=forced_unassessed,
        forced_review_inactive_n=forced_inactive,
        forced_review_emerged_n=forced_emerged,
        forced_review_persisted_n=forced_persisted,
        forced_review_resolved_n=forced_resolved,
        scanner_config_unassessed_n=scanner_unassessed,
        scanner_config_same_n=scanner_same,
        scanner_config_changed_n=scanner_changed,
        priority_delta_n=len(priority),
        mean_priority_delta=_mean_or_none(priority),
        confidence_delta_n=len(confidence),
        mean_confidence_delta=_mean_or_none(confidence),
        novelty_delta_n=len(novelty),
        mean_novelty_delta=_mean_or_none(novelty),
    )
```

Add:

```python
def _build_summaries(
    transitions: tuple[ReplayCohortTransition, ...],
) -> tuple[ReplayCohortSummary, ...]:
    grouped = {}
    for item in transitions:
        grouped.setdefault(
            (item.routing_intent, item.horizon_cycles),
            [],
        ).append(item)

    summaries = [
        _build_summary(intent, horizon, rows)
        for (intent, horizon), rows in grouped.items()
    ]
    return tuple(
        sorted(
            summaries,
            key=lambda item: (
                item.horizon_cycles,
                item.routing_intent.value,
            ),
        )
    )
```

Update `evaluate_replay_cohort` to build summaries and compute final result hash after both transitions and summaries exist.

- [ ] **Step 6: Export public interfaces**

Modify `src/decision_lab/__init__.py`:

```python
from .replay_cohort import (
    ContradictionTransition,
    EvidenceClass,
    FuturePresence,
    IndependentEvidenceState,
    ReplayCohortResult,
    ReplayCohortSummary,
    ReplayCohortTransition,
    RoutingIntent,
    TierTransition,
    evaluate_replay_cohort,
)
```

Add all 10 names to sorted `__all__`.

Do not export private helpers.

- [ ] **Step 7: Run Task-4 tests and full regression**

Run:

```bash
pytest -q tests/test_replay_cohort.py
pytest -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/decision_lab/replay_cohort.py src/decision_lab/__init__.py tests/test_replay_cohort.py
git commit -m "test: prove replay cohort walk-forward evaluation"
```

---

### Task 5: Final acceptance gaps, purity audit, Ruff, and whole-branch review

**Files:**
- Verify: `src/decision_lab/replay_cohort.py`
- Verify: `src/decision_lab/__init__.py`
- Verify: `tests/test_replay_cohort.py`
- Review-only: all forbidden downstream modules.

**Interfaces:**
- Produces verification evidence only.
- No new public behavior.

- [ ] **Step 1: Add final RED tests for forced-review inconsistency, cycle timestamps, scanner config multiplicity, and source-population coverage**

Append:

```python
def test_forced_review_flag_mismatch_is_rejected():
    record = _registered_archive(
        themes=("RiskTheme",),
        observations=(
            _independent(
                "RiskTheme",
                "risk",
                SupportDirection.CONTRADICTING,
            ),
        ),
    )
    result = record.replay_result
    allocation = replace(
        result.allocations[0],
        forced_review=False,
    )
    theme_record = replace(
        result.theme_records[0],
        allocation=allocation,
    )
    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            allocations=(allocation,),
            theme_records=(theme_record,),
        )
    )

    with pytest.raises(ValueError, match="forced-review flag mismatch"):
        evaluate_replay_cohort((bad,), horizons=(1,))


def test_cycle_timestamp_mismatch_is_rejected():
    record = _archive()
    result = record.replay_result
    scan = replace(
        result.scan_results[0],
        as_of="2026-09-18",
    )
    allocation = replace(
        result.allocations[0],
        source_scan_result_hash=canonical_hash(asdict(scan)),
    )
    theme_record = replace(
        result.theme_records[0],
        scan_result=scan,
        allocation=allocation,
    )
    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            scan_results=(scan,),
            allocations=(allocation,),
            theme_records=(theme_record,),
        )
    )

    with pytest.raises(ValueError, match="inconsistent replay theme record"):
        evaluate_replay_cohort((bad,), horizons=(1,))


def test_multiple_scanner_config_hashes_in_cycle_are_rejected():
    record = _registered_archive(
        themes=("ATheme", "BTheme"),
        observations=(
            _independent(
                "ATheme",
                "a",
                SupportDirection.SUPPORTING,
            ),
            _independent(
                "BTheme",
                "b",
                SupportDirection.SUPPORTING,
            ),
        ),
    )
    result = record.replay_result
    scans = list(result.scan_results)
    scans[1] = replace(scans[1], config_hash="different")
    scan_by_theme = {item.theme_id: item for item in scans}
    allocations = []
    records = []
    for allocation in result.allocations:
        scan = scan_by_theme[allocation.theme_id]
        changed_allocation = replace(
            allocation,
            source_scan_result_hash=canonical_hash(asdict(scan)),
        )
        allocations.append(changed_allocation)
    allocation_by_theme = {
        item.theme_id: item for item in allocations
    }
    for theme_record in result.theme_records:
        if theme_record.replay_status is ReplayStatus.ROUTED:
            records.append(
                replace(
                    theme_record,
                    scan_result=scan_by_theme[theme_record.theme_id],
                    allocation=allocation_by_theme[theme_record.theme_id],
                )
            )
        else:
            records.append(theme_record)

    bad = _archive_from_semantically_modified_result(
        replace(
            result,
            scan_results=tuple(scans),
            allocations=tuple(allocations),
            theme_records=tuple(records),
        )
    )

    with pytest.raises(
        ValueError,
        match="multiple scanner config hashes in replay cycle",
    ):
        evaluate_replay_cohort((bad,), horizons=(1,))
```

These tests should RED if any Review Focus boundary is missing; fix minimally in the owning validation/routing helper.

- [ ] **Step 2: Run fresh full regression**

Run:

```bash
pytest -q
```

Expected: all tests PASS after any required minimal RED→GREEN fixes.

- [ ] **Step 3: Run changed-files Ruff**

Run:

```bash
python -m ruff check \
  src/decision_lab/replay_cohort.py \
  src/decision_lab/__init__.py \
  tests/test_replay_cohort.py
```

Expected: exit 0.

- [ ] **Step 4: Audit forbidden semantic drift and prohibited concepts**

Verify no diffs to:

```text
src/decision_lab/replay.py
src/decision_lab/replay_archive.py
src/decision_lab/scanner.py
src/decision_lab/research_budget.py
src/decision_lab/market_observation.py
src/decision_lab/outcomes.py
src/decision_lab/themes.py
src/decision_lab/universe.py
src/decision_lab/ledger.py
src/decision_lab/tape.py
src/decision_lab/playbooks.py
```

Verify final PR contains no persistent new `.github/workflows` file.

Verify `replay_cohort.py` does not import/call:

```text
pathlib
os
json
requests
urllib
httpx
yfinance
alpaca
polygon
evaluate_forward_outcomes
missed_upside
summarize_decisions
datetime.now
random
uuid
subprocess
socket
read_replay_archive
```

Verify public dataclasses contain no field whose name includes:

```text
return
alpha
mae
mfe
accuracy
success
failure
reward
performance_score
```

The substring `future_` is allowed; this check is field-name-specific, not raw source substring matching.

- [ ] **Step 5: Whole-branch review against Review Focus**

Inspect specifically:

- duplicate archive hash rejection happens before ambiguous-cycle handling;
- date-only normalization is UTC EOD and exact same normalized instant is ambiguous;
- archive semantic validity is rebuilt with `build_replay_archive_record`;
- top-level batch/scan/allocation coverage equals theme-record expectations;
- registered theme always owns a market batch; unknown theme never does;
- observation themes all exist in current theme records;
- allocation source-scan hashes are verified;
- forced-review flags/reasons/tier combinations are supported exactly;
- independent source metadata is consistent before source collapse;
- contradiction resolution requires independent evidence on both source/future sides;
- `NOT_PRESENT`, `PRESENT+NO_OBSERVATION`, and `RIGHT_CENSORED` stay distinct;
- no backward transition is created for future-only themes;
- right-censored transitions are emitted rather than dropped;
- summary partitions equal source_n exactly;
- means ignore None and expose contributing N;
- scanner config change is descriptive and unavailable rows are explicit;
- budget config is never inferred;
- routing tier is never described as downstream research execution;
- no price/trading outcome imports or fields;
- input/result hashes bind only the approved cohort semantics;
- input records are not mutated.

Any Critical/Important issue gets one TDD fix pass:

1. write reproducing RED test;
2. verify RED;
3. implement minimal fix;
4. rerun targeted test;
5. rerun full suite and Ruff.

- [ ] **Step 6: Exact-final-tree verification**

On the exact final branch head:

```bash
pytest -q
python -m ruff check \
  src/decision_lab/replay_cohort.py \
  src/decision_lab/__init__.py \
  tests/test_replay_cohort.py
```

Record exact pytest count/time and Ruff result.

- [ ] **Step 7: Keep branch unmerged**

Present integration options only after exact-final-tree verification. Do not merge until explicit user authorization.
