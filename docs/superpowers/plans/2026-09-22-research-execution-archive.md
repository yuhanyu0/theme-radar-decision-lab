# Immutable Research Execution Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist Increment-8 ResearchWorkOrder and ResearchDossier objects as immutable, content-addressed historical records with replay provenance, full WorkOrder policy archival, explicit optional Dossier-parent lineage, strict typed readers, and append-only safe writers.

**Architecture:** Create one focused `research_execution_archive.py` module. Pure record builders first validate and freeze WorkOrder/Dossier lineage; typed readers then reconstruct and revalidate every recoverable semantic invariant; filesystem writers reuse those validators and add deterministic JSON, destination policy, exclusive creation, idempotence, and symlink containment. Archive graph scanning, fork/orphan interpretation, progression metrics, and Decision Readiness remain out of scope.

**Tech Stack:** Python 3.11, dataclasses, Enum, datetime, json, os, pathlib, existing `canonical_hash`, existing replay/research-execution types, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-22-research-execution-archive-design.md`

## Global Constraints

- WorkOrder archive schema version is exactly `"0.1"`, content type `"research_work_order"`, producer `"theme-radar-decision-lab/research-execution-archive@0.1"`.
- Dossier archive schema version is exactly `"0.1"`, content type `"research_dossier"`, producer `"theme-radar-decision-lab/research-execution-archive@0.1"`.
- WorkOrder archives freeze the complete normalized `ResearchWorkOrderPolicy`, not only `policy_hash`.
- WorkOrder archive construction validates the supplied `ReplayArchiveRecord` and independently checks source routing provenance through `evaluate_replay_cohort((record,), horizons=(1,))`.
- Dossier archive identity is `archive_record_hash`; Dossier filenames are `<archive_record_hash>.json`, not `<dossier_hash>.json`.
- Dossier archives embed the complete typed `ResearchWorkOrderArchiveRecord`.
- Dossier parent lineage is optional and explicit; builders accept a typed parent record, never search storage for a parent.
- Parent-child Dossiers require the same WorkOrder and strictly increasing normalized `evidence_as_of`.
- Evidence/status/requirement monotonicity is not required; COMPLETE -> PARTIAL and evidence retraction remain archive-valid.
- Standalone readers never scan for parent existence, detect forks/orphans, or select a latest snapshot.
- `ResearchDossier.input_hash` raw-input provenance cannot be independently recomputed; reader verifies its SHA-256 shape and its inclusion in `dossier_hash`.
- Readers recompute every recoverable Dossier semantic invariant: requirement partition, status, company assessments, linkage semantics, independent-source counts, findings, contradiction/unresolved flags, and Dossier hash.
- `FrozenResearchEvidence.source_hash` and `payload_hash`, and `NormalizedCompanySnapshot.normalized_payload_hash`, remain commitments when original omitted payloads are unavailable.
- Public archive root resolves to a path ending `recomputed/research_execution`; PUBLIC write requires literal `public_safe is True`.
- PUBLIC and PRIVATE writes reject any resolved path containing contiguous `ledger/live`.
- Writers use `os.O_WRONLY | os.O_CREAT | os.O_EXCL`; no overwrite behavior exists.
- Identical valid pre-existing records are idempotent with `created=False`; invalid/conflicting existing files are hard conflicts.
- No network/provider imports; no ambient semantic time; no randomness.
- No archive index, manifest, SQLite, directory scan, progression evaluator, Decision Readiness, Tape, Playbook, Decision Object, research-value metric, or price outcome.
- Existing `research_execution.py`, replay/archive/cohort, scanner/budget, evidence/adapters/linkage, Tape/Playbook/Decision/outcomes, theme/universe/ledger behavior must not change.
- Branch remains unmerged until exact-final-tree pytest, changed-files Ruff, whole-branch review, and final PR/file audit are green.

## Review Focus

1. **False replay provenance:** a WorkOrder that preserves real replay hashes but rehashes a different internally valid routing state must be rejected against the source replay's actual cohort transition.
2. **False Dossier semantic closure:** rehashed Dossier fields such as satisfied requirements, status, independent counts, company cautions, linkage status, or contradiction flags must be recomputed and rejected if inconsistent.
3. **Archive identity collision:** the same Dossier snapshot with different explicit parent lineage must produce distinct archive-record hashes and distinct filenames while preserving the same `dossier_hash`.
4. **Filesystem aliasing:** symlinked cycle/work-order directories, pre-existing file symlinks, noncanonical PUBLIC roots, and `ledger/live` aliases must not redirect writes outside policy.
5. **Commitment overclaim:** readers must validate the shape/commitment of omitted raw evidence and Dossier input hashes without claiming to regenerate data that Increment 8 intentionally did not retain.

---

## File map

- Create `src/decision_lab/research_execution_archive.py`
  - archive enums/dataclasses/constants;
  - UTC/hash/strict-value helpers;
  - WorkOrder policy + replay provenance validator;
  - Dossier recoverable-semantic validator;
  - WorkOrder/Dossier archive builders;
  - strict nested JSON decoders;
  - read/verify/path helpers;
  - deterministic serialization;
  - destination policy and append-only writers.
- Create `tests/test_research_execution_archive.py`
  - deterministic source replay + WorkOrder fixtures;
  - WorkOrder archive provenance tests;
  - Dossier/parent/fork/non-monotonic tests;
  - semantic-tamper decoder tests;
  - path/write/public/private/symlink tests.
- Modify `src/decision_lab/__init__.py` for public exports only.
- Do not modify semantics in existing modules.

---

### Task 1: WorkOrder archive record, full policy provenance, replay-routing provenance, and pure path identity

**Files:**
- Create: `src/decision_lab/research_execution_archive.py`
- Create: `tests/test_research_execution_archive.py`

**Interfaces:**
- Consumes:
  - `ReplayArchiveRecord`
  - `build_replay_archive_record`
  - `evaluate_replay_cohort`
  - `ResearchWorkOrder`
  - `ResearchWorkOrderPolicy`
  - Increment-8 private deterministic helpers `_normalize_policy`, `_build_requirements`, `_validate_work_order_hash`
  - `canonical_hash`
- Produces:
  - `ResearchArchiveDestinationVisibility`
  - `ResearchArchiveWriteResult`
  - `ResearchWorkOrderArchiveRecord`
  - `build_research_work_order_archive_record(...)`
  - `research_work_order_archive_path(...)`

- [ ] **Step 1: Write deterministic replay/WorkOrder fixtures and RED happy-path test**

Create `tests/test_research_execution_archive.py`:

```python
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from decision_lab.ledger import canonical_hash
from decision_lab.market_observation import (
    MarketBar,
    MarketObservationConfig,
    MarketObservationMode,
    MarketObservationSpec,
)
from decision_lab.replay import ReplayCycleInput, ThemeReplayInput, run_replay_cycle
from decision_lab.replay_archive import build_replay_archive_record
from decision_lab.research_budget import ResearchBudgetConfig, ResearchTier
from decision_lab.research_execution import (
    ResearchAuthorization,
    ResearchMode,
    ResearchWorkOrderPolicy,
    build_research_work_order,
)
from decision_lab.research_execution_archive import (
    ResearchWorkOrderArchiveRecord,
    build_research_work_order_archive_record,
    research_work_order_archive_path,
)
from decision_lab.scanner import (
    ScannerConfig,
    SupportDirection,
    ThemeScanObservation,
)
from decision_lab.themes import (
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemeLifecycleState,
    ThemePackage,
)
from decision_lab.universe import Candidate, ThemeLayer, ThemeUniverse


def _package(theme="ArchiveResearchTheme"):
    universe = ThemeUniverse(
        theme=theme,
        version="u1",
        generated_at="2026-09-19T00:00:00Z",
    )
    universe.add_layer(ThemeLayer("primary"))
    universe.add_candidate(
        Candidate(
            ticker="AAA",
            theme=theme,
            layer="primary",
            effective_from="2026-01-01",
            provenance=("fixture:AAA",),
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
        evidence_adapter="industrials_infrastructure",
        version="p1",
        source_path="fixture",
    )


def _source_observation(theme, *, direction=SupportDirection.SUPPORTING):
    return ThemeScanObservation(
        theme_id=theme,
        as_of="2026-09-19",
        source_type="derived_feature",
        source_ref=f"fixture:{theme}:{direction.value}",
        discovery_signal=1.0,
        structure_signal=1.0,
        persistence_signal=1.0,
        breadth_signal=1.0,
        relative_strength_signal=1.0,
        novelty_signal=1.0,
        support_direction=direction,
        evidence_refs=(f"fixture:{theme}",),
        is_independent=True,
        observed_or_inferred="observed",
    )


def _replay_archive_and_order(
    *,
    direction=SupportDirection.SUPPORTING,
    policy=None,
):
    package = _package()
    theme = package.definition.theme_id
    result = run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of="2026-09-19",
            themes=(
                ThemeReplayInput(
                    package=package,
                    market_spec=MarketObservationSpec(
                        theme_id=theme,
                        mode=MarketObservationMode.BASKET,
                        benchmark="SPY",
                        current_return_sessions=1,
                        prior_return_sessions=1,
                        min_basket_members=1,
                        version="archive-test",
                    ),
                    market_config=MarketObservationConfig(),
                    bars=(
                        MarketBar(
                            symbol="SPY",
                            session_date="2026-09-19",
                            available_at="2026-09-19T21:00:00+00:00",
                            close=100.0,
                        ),
                    ),
                    market_source_ref="fixture:archive-market",
                ),
            ),
            external_observations=(
                _source_observation(theme, direction=direction),
            ),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
    replay_archive = build_replay_archive_record(result)
    raw_policy = (
        ResearchWorkOrderPolicy()
        if policy is None
        else policy
    )
    work_order_policy = replace(
        raw_policy,
        theme_reassessment_dimensions=tuple(
            sorted(raw_policy.theme_reassessment_dimensions)
        ),
        industrials_company_dimensions=tuple(
            sorted(raw_policy.industrials_company_dimensions)
        ),
        biotech_company_dimensions=tuple(
            sorted(raw_policy.biotech_company_dimensions)
        ),
    )
    mode = (
        ResearchMode.COMPANY_DEEP_DIVE
        if direction is SupportDirection.SUPPORTING
        else ResearchMode.THEME_REASSESSMENT
    )
    order = build_research_work_order(
        replay_archive,
        theme,
        mode,
        theme_package=package,
        target_tickers=("AAA",) if mode is ResearchMode.COMPANY_DEEP_DIVE else (),
        policy=work_order_policy,
    )
    return replay_archive, order, work_order_policy


def test_work_order_archive_builder_freezes_policy_and_replay_lineage():
    replay_archive, order, policy = _replay_archive_and_order()

    first = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    second = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )

    assert isinstance(first, ResearchWorkOrderArchiveRecord)
    assert first == second
    assert first.source_cycle_as_of == replay_archive.cycle_as_of
    assert (
        first.source_replay_archive_record_hash
        == replay_archive.archive_record_hash
    )
    assert first.source_replay_result_hash == replay_archive.replay_result_hash
    assert first.work_order_hash == order.work_order_hash
    assert first.work_order == order
    assert first.work_order_policy == policy
    assert len(first.archive_record_hash) == 64
    assert first.archive_record_hash == first.archive_record_hash.lower()
```

- [ ] **Step 2: Add RED policy mismatch and replay-routing provenance tests**

```python
def test_work_order_archive_rejects_mismatched_policy():
    replay_archive, order, policy = _replay_archive_and_order()
    wrong = replace(
        policy,
        minimum_independent_sources=policy.minimum_independent_sources + 1,
    )

    with pytest.raises(
        ValueError,
        match="research work order policy mismatch",
    ):
        build_research_work_order_archive_record(
            replay_archive,
            order,
            work_order_policy=wrong,
        )


def test_work_order_archive_rejects_rehashed_false_routing_provenance():
    replay_archive, order, policy = _replay_archive_and_order()
    # Build a fully internally valid forced-review-shaped WorkOrder directly.
    # The actual source replay remains ordinary FULL.
    forced_replay, forced_order, _ = _replay_archive_and_order(
        direction=SupportDirection.CONTRADICTING
    )
    tampered = replace(
        forced_order,
        source_archive_record_hash=replay_archive.archive_record_hash,
        source_replay_result_hash=replay_archive.replay_result_hash,
        source_cycle_as_of=replay_archive.cycle_as_of,
        work_order_hash="0" * 64,
    )
    payload = asdict(tampered)
    payload.pop("work_order_hash")
    tampered = replace(
        tampered,
        work_order_hash=canonical_hash(payload),
    )

    assert forced_replay.replay_result_hash != replay_archive.replay_result_hash
    with pytest.raises(
        ValueError,
        match="research work order replay lineage mismatch",
    ):
        build_research_work_order_archive_record(
            replay_archive,
            tampered,
            work_order_policy=policy,
        )
```

- [ ] **Step 3: Add RED invalid replay and path tests**

```python
def test_work_order_archive_rejects_invalid_source_replay_archive():
    replay_archive, order, policy = _replay_archive_and_order()
    invalid = replace(
        replay_archive,
        archive_record_hash="0" * 64,
    )

    with pytest.raises(
        ValueError,
        match="invalid source replay archive record",
    ):
        build_research_work_order_archive_record(
            invalid,
            order,
            work_order_policy=policy,
        )


def test_work_order_archive_path_uses_source_cycle_and_work_order_hash(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    root = tmp_path / "recomputed" / "research_execution"

    path = research_work_order_archive_path(record, root)

    assert path == (
        root
        / "work_orders"
        / "2026-09-19"
        / f"{order.work_order_hash}.json"
    )
    assert not root.exists()
```

- [ ] **Step 4: Run Task-1 tests and verify RED**

Run:

```bash
pytest -q tests/test_research_execution_archive.py
```

Expected: collection failure because `decision_lab.research_execution_archive` does not exist.

- [ ] **Step 5: Implement constants, archive types, UTC/hash helpers**

Create `src/decision_lab/research_execution_archive.py`:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from math import isfinite
from pathlib import Path

from .ledger import canonical_hash
from .replay_archive import ReplayArchiveRecord, build_replay_archive_record
from .replay_cohort import evaluate_replay_cohort
from .research_execution import (
    ResearchDossier,
    ResearchMode,
    ResearchRequirement,
    ResearchRequirementScope,
    ResearchWorkOrder,
    ResearchWorkOrderPolicy,
    _build_requirements,
    _normalize_policy,
    _validate_work_order_hash,
)

SCHEMA_VERSION = "0.1"
PRODUCER = "theme-radar-decision-lab/research-execution-archive@0.1"
WORK_ORDER_CONTENT_TYPE = "research_work_order"
DOSSIER_CONTENT_TYPE = "research_dossier"


class ResearchArchiveDestinationVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"


@dataclass(frozen=True)
class ResearchArchiveWriteResult:
    path: Path
    created: bool
    content_hash: str
    archive_record_hash: str


@dataclass(frozen=True)
class ResearchWorkOrderArchiveRecord:
    schema_version: str
    content_type: str
    producer: str
    source_cycle_as_of: str
    source_replay_archive_record_hash: str
    source_replay_result_hash: str
    work_order_hash: str
    work_order_policy: ResearchWorkOrderPolicy
    work_order: ResearchWorkOrder
    archive_record_hash: str


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    if "T" not in value and " " not in value:
        dt = dt.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )
    return dt


def _cycle_date(value: str) -> str:
    return _parse_utc(value).date().isoformat()


def _validate_sha256(value: str, *, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"invalid {field_name}")
```

- [ ] **Step 6: Implement WorkOrder policy and replay-provenance validation**

```python
def _validate_work_order_policy(
    order: ResearchWorkOrder,
    policy: ResearchWorkOrderPolicy,
) -> ResearchWorkOrderPolicy:
    try:
        normalized = _normalize_policy(policy)
        _validate_work_order_hash(order)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid research work order") from exc

    if canonical_hash(asdict(normalized)) != order.policy_hash:
        raise ValueError("research work order policy mismatch")
    if (
        normalized.minimum_independent_sources
        != order.minimum_independent_sources
        or normalized.minimum_independent_sources_per_company
        != order.minimum_independent_sources_per_company
    ):
        raise ValueError("research work order policy mismatch")

    try:
        expected_requirements = _build_requirements(
            mode=order.research_mode,
            targets=order.targets,
            adapter_name=order.evidence_adapter,
            policy=normalized,
        )
    except (TypeError, ValueError, AssertionError) as exc:
        raise ValueError("research work order policy mismatch") from exc

    if expected_requirements != order.requirements:
        raise ValueError("research work order policy mismatch")
    return normalized


def _validate_source_replay(
    replay_archive: ReplayArchiveRecord,
) -> None:
    try:
        rebuilt = build_replay_archive_record(
            replay_archive.replay_result
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid source replay archive record") from exc
    if rebuilt != replay_archive:
        raise ValueError("invalid source replay archive record")


def _validate_replay_work_order_lineage(
    replay_archive: ReplayArchiveRecord,
    order: ResearchWorkOrder,
) -> None:
    if (
        order.source_archive_record_hash
        != replay_archive.archive_record_hash
        or order.source_replay_result_hash
        != replay_archive.replay_result_hash
        or order.source_cycle_as_of
        != replay_archive.cycle_as_of
    ):
        raise ValueError("research work order replay lineage mismatch")

    cohort = evaluate_replay_cohort(
        (replay_archive,),
        horizons=(1,),
    )
    matches = [
        item
        for item in cohort.transitions
        if item.theme_id == order.theme_id
    ]
    if len(matches) != 1:
        raise ValueError("research work order replay lineage mismatch")
    transition = matches[0]
    if (
        transition.routing_intent is not order.source_routing_intent
        or transition.source_registered != order.source_registered
        or transition.source_tier is not order.source_allocated_tier
        or transition.source_forced_review != order.source_forced_review
    ):
        raise ValueError("research work order replay lineage mismatch")
```

- [ ] **Step 7: Implement WorkOrder archive semantic validation, builder, and path**

```python
def _work_order_archive_payload_without_hash(
    record: ResearchWorkOrderArchiveRecord,
) -> dict[str, object]:
    payload = asdict(record)
    payload.pop("archive_record_hash")
    return payload


def _validate_work_order_archive_record(
    record: ResearchWorkOrderArchiveRecord,
) -> None:
    if (
        record.schema_version != SCHEMA_VERSION
        or record.content_type != WORK_ORDER_CONTENT_TYPE
        or record.producer != PRODUCER
    ):
        raise ValueError("unsupported research work-order archive contract")

    for field_name, value in (
        ("source replay archive record hash", record.source_replay_archive_record_hash),
        ("source replay result hash", record.source_replay_result_hash),
        ("work order hash", record.work_order_hash),
        ("research work-order archive hash", record.archive_record_hash),
    ):
        _validate_sha256(value, field_name=field_name)

    normalized_policy = _validate_work_order_policy(
        record.work_order,
        record.work_order_policy,
    )
    if normalized_policy != record.work_order_policy:
        raise ValueError("research work order policy mismatch")

    if (
        record.source_cycle_as_of
        != record.work_order.source_cycle_as_of
        or record.source_replay_archive_record_hash
        != record.work_order.source_archive_record_hash
        or record.source_replay_result_hash
        != record.work_order.source_replay_result_hash
        or record.work_order_hash
        != record.work_order.work_order_hash
    ):
        raise ValueError("research work-order archive nested identity mismatch")

    expected = canonical_hash(
        _work_order_archive_payload_without_hash(record)
    )
    if expected != record.archive_record_hash:
        raise ValueError("research work-order archive hash mismatch")


def build_research_work_order_archive_record(
    replay_archive: ReplayArchiveRecord,
    work_order: ResearchWorkOrder,
    *,
    work_order_policy: ResearchWorkOrderPolicy,
) -> ResearchWorkOrderArchiveRecord:
    _validate_source_replay(replay_archive)
    normalized_policy = _validate_work_order_policy(
        work_order,
        work_order_policy,
    )
    _validate_replay_work_order_lineage(
        replay_archive,
        work_order,
    )

    seed = ResearchWorkOrderArchiveRecord(
        schema_version=SCHEMA_VERSION,
        content_type=WORK_ORDER_CONTENT_TYPE,
        producer=PRODUCER,
        source_cycle_as_of=work_order.source_cycle_as_of,
        source_replay_archive_record_hash=(
            replay_archive.archive_record_hash
        ),
        source_replay_result_hash=replay_archive.replay_result_hash,
        work_order_hash=work_order.work_order_hash,
        work_order_policy=normalized_policy,
        work_order=work_order,
        archive_record_hash="0" * 64,
    )
    record = replace(
        seed,
        archive_record_hash=canonical_hash(
            _work_order_archive_payload_without_hash(seed)
        ),
    )
    _validate_work_order_archive_record(record)
    return record


def research_work_order_archive_path(
    record: ResearchWorkOrderArchiveRecord,
    archive_root: str | Path,
) -> Path:
    return (
        Path(archive_root)
        / "work_orders"
        / _cycle_date(record.source_cycle_as_of)
        / f"{record.work_order_hash}.json"
    )
```

- [ ] **Step 8: Run Task-1 tests and full regression**

Run:

```bash
pytest -q tests/test_research_execution_archive.py
pytest -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/decision_lab/research_execution_archive.py tests/test_research_execution_archive.py
git commit -m "feat: add immutable research work order archives"
```

---

### Task 2: Dossier archive record, recoverable semantic closure, parent lineage, fork/non-monotonic support, and pure path identity

**Files:**
- Modify: `src/decision_lab/research_execution_archive.py`
- Modify: `tests/test_research_execution_archive.py`

**Interfaces:**
- Consumes:
  - Task-1 `ResearchWorkOrderArchiveRecord`
  - `ResearchDossier` and Increment-8 immutable snapshot types
  - `SOURCE_PRIORITY`
  - `LinkageResult`
  - Increment-8 `_linkage_status`
- Produces:
  - `ResearchDossierArchiveRecord`
  - `build_research_dossier_archive_record(...)`
  - `research_dossier_archive_path(...)`
  - private recoverable-semantic Dossier validators used later by readers.

- [ ] **Step 1: Add deterministic theme-Dossier and company-Dossier helpers**

Append imports:

```python
from decision_lab.evidence import EvidenceRecord
from decision_lab.hierarchical import HierarchicalLinkageResult
from decision_lab.linkage import LinkageResult
from decision_lab.research_execution import (
    CompanyLinkageSubmission,
    CompanyResearchSubmission,
    ResearchDossierStatus,
    ResearchEvidenceDirection,
    ResearchEvidenceInput,
    ResearchExecutionClosure,
    ResearchFinding,
    ResearchFindingKind,
    build_research_dossier,
)
from decision_lab.research_execution_archive import (
    ResearchDossierArchiveRecord,
    build_research_dossier_archive_record,
    research_dossier_archive_path,
)
```

Add:

```python
def _hashed_evidence(
    *,
    evidence_id,
    source_ref,
    payload,
    theme="ArchiveResearchTheme",
    ticker=None,
    source_type="official_macro",
):
    raw = EvidenceRecord(
        evidence_id=evidence_id,
        observed_at="2026-09-20T12:00:00+00:00",
        retrieved_at="2026-09-20T13:00:00+00:00",
        market_asof=None,
        ticker=ticker,
        theme=theme,
        source_type=source_type,
        source_ref=source_ref,
        fact_type="archive_research_fact",
        payload=dict(payload),
        is_observed_fact=True,
    )
    return raw.with_hash()


def _theme_work_order_archive():
    replay_archive, order, policy = _replay_archive_and_order(
        direction=SupportDirection.CONTRADICTING,
        policy=replace(
            ResearchWorkOrderPolicy(),
            minimum_independent_sources=1,
        ),
    )
    archive = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    return archive, order


def _theme_dossier(
    order,
    *,
    evidence_as_of,
    closure=ResearchExecutionClosure.OPEN,
    include_all_requirements=True,
):
    evidence = _hashed_evidence(
        evidence_id=f"ev:{evidence_as_of}",
        source_ref=f"official:{evidence_as_of}",
        payload={"state": evidence_as_of},
    )
    dimensions = (
        tuple(item.dimension for item in order.requirements)
        if include_all_requirements
        else (order.requirements[0].dimension,)
    )
    return build_research_dossier(
        order,
        evidence_as_of=evidence_as_of,
        closure=closure,
        evidence_inputs=(
            ResearchEvidenceInput(
                evidence=evidence,
                independent=True,
                direction=ResearchEvidenceDirection.CONTRADICTING,
                dimensions=dimensions,
                target_ticker=None,
            ),
        ),
    )


def _company_archive_and_dossier():
    replay_archive, order, policy = _replay_archive_and_order(
        policy=replace(
            ResearchWorkOrderPolicy(),
            industrials_company_dimensions=("growth",),
            minimum_independent_sources=1,
            minimum_independent_sources_per_company=1,
        )
    )
    work_archive = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    evidence = _hashed_evidence(
        evidence_id="ev:AAA",
        source_ref="sec:AAA",
        payload={"revenue_growth": 0.2},
        ticker="AAA",
        source_type="sec_filing",
    )
    linkage = LinkageResult(
        ticker="AAA",
        control_name="theme-minus-AAA",
        window=63,
        correlation=0.6,
        beta=0.9,
        r2=0.4,
        residual_mean=0.0,
        residual_vol=0.02,
        beta_stability=0.8,
        decoupling_score=0.3,
        circularity_warning=False,
        observations=63,
    )
    dossier = build_research_dossier(
        order,
        evidence_as_of="2026-09-20T23:00:00+00:00",
        closure=ResearchExecutionClosure.OPEN,
        evidence_inputs=(
            ResearchEvidenceInput(
                evidence=evidence,
                independent=True,
                direction=ResearchEvidenceDirection.SUPPORTING,
                dimensions=("growth",),
                target_ticker="AAA",
            ),
        ),
        company_submissions=(
            CompanyResearchSubmission(
                ticker="AAA",
                as_of="2026-09-20T20:00:00+00:00",
                adapter_name="industrials_infrastructure",
                raw_facts={"revenue_growth": 0.2},
                evidence_source_hashes=(evidence.source_hash,),
            ),
        ),
        linkage_submissions=(
            CompanyLinkageSubmission(
                ticker="AAA",
                linkage=linkage,
            ),
        ),
    )
    assert dossier.status is ResearchDossierStatus.COMPLETE
    return work_archive, dossier
```

- [ ] **Step 2: Add RED root/child/strict-time tests**

```python
def test_dossier_archive_root_and_child_preserve_explicit_lineage():
    work_archive, order = _theme_work_order_archive()
    root_dossier = _theme_dossier(
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        include_all_requirements=False,
    )
    root = build_research_dossier_archive_record(
        work_archive,
        root_dossier,
    )
    child_dossier = _theme_dossier(
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        include_all_requirements=True,
    )
    child = build_research_dossier_archive_record(
        work_archive,
        child_dossier,
        prior_dossier_archive=root,
    )

    assert isinstance(root, ResearchDossierArchiveRecord)
    assert root.prior_dossier_archive_record_hash is None
    assert (
        child.prior_dossier_archive_record_hash
        == root.archive_record_hash
    )
    assert child.work_order_archive == work_archive
    assert child.dossier_hash == child_dossier.dossier_hash


@pytest.mark.parametrize(
    "child_time",
    [
        "2026-09-20T20:00:00+00:00",
        "2026-09-20T16:00:00-04:00",
        "2026-09-20T19:59:59+00:00",
    ],
)
def test_dossier_parent_must_be_strictly_earlier(child_time):
    work_archive, order = _theme_work_order_archive()
    parent = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
        ),
    )
    child_dossier = _theme_dossier(
        order,
        evidence_as_of=child_time,
    )

    with pytest.raises(
        ValueError,
        match="research dossier parent must be strictly earlier",
    ):
        build_research_dossier_archive_record(
            work_archive,
            child_dossier,
            prior_dossier_archive=parent,
        )
```

- [ ] **Step 3: Add RED non-monotonic/fork/archive-identity tests**

```python
def test_dossier_archive_allows_complete_to_partial_and_forks():
    work_archive, order = _theme_work_order_archive()
    complete = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
            include_all_requirements=True,
        ),
    )
    partial_a = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-21T20:00:00+00:00",
            include_all_requirements=False,
        ),
        prior_dossier_archive=complete,
    )
    partial_b = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-22T20:00:00+00:00",
            include_all_requirements=False,
        ),
        prior_dossier_archive=complete,
    )

    assert complete.dossier.status is ResearchDossierStatus.COMPLETE
    assert partial_a.dossier.status is ResearchDossierStatus.PARTIAL
    assert partial_b.dossier.status is ResearchDossierStatus.PARTIAL
    assert (
        partial_a.prior_dossier_archive_record_hash
        == complete.archive_record_hash
    )
    assert (
        partial_b.prior_dossier_archive_record_hash
        == complete.archive_record_hash
    )


def test_same_dossier_with_different_parent_lineage_has_distinct_archive_identity(tmp_path):
    work_archive, order = _theme_work_order_archive()
    parent_a = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T18:00:00+00:00",
        ),
    )
    parent_b = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T19:00:00+00:00",
        ),
    )
    dossier = _theme_dossier(
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
    )
    first = build_research_dossier_archive_record(
        work_archive,
        dossier,
        prior_dossier_archive=parent_a,
    )
    second = build_research_dossier_archive_record(
        work_archive,
        dossier,
        prior_dossier_archive=parent_b,
    )

    assert first.dossier_hash == second.dossier_hash
    assert first.archive_record_hash != second.archive_record_hash
    first_path = research_dossier_archive_path(first, tmp_path)
    second_path = research_dossier_archive_path(second, tmp_path)
    assert first_path != second_path
    assert first_path.name == f"{first.archive_record_hash}.json"
    assert second_path.name == f"{second.archive_record_hash}.json"
```

- [ ] **Step 4: Add RED rehashed Dossier semantic-tamper tests**

```python
def _rehash_dossier(dossier, **changes):
    seed = replace(
        dossier,
        **changes,
        dossier_hash="0" * 64,
    )
    payload = asdict(seed)
    payload.pop("dossier_hash")
    return replace(seed, dossier_hash=canonical_hash(payload))


def test_dossier_archive_rejects_rehashed_false_requirement_partition():
    work_archive, dossier = _company_archive_and_dossier()
    tampered = _rehash_dossier(
        dossier,
        satisfied_requirements=(),
        unsatisfied_requirements=dossier.satisfied_requirements,
    )

    with pytest.raises(ValueError):
        build_research_dossier_archive_record(
            work_archive,
            tampered,
        )


def test_dossier_archive_rejects_rehashed_false_company_assessment():
    work_archive, dossier = _company_archive_and_dossier()
    assessment = dossier.company_assessments[0]
    tampered_assessment = replace(
        assessment,
        independent_source_count=99,
    )
    tampered = _rehash_dossier(
        dossier,
        company_assessments=(tampered_assessment,),
    )

    with pytest.raises(
        ValueError,
        match="inconsistent research company assessment",
    ):
        build_research_dossier_archive_record(
            work_archive,
            tampered,
        )



def test_dossier_archive_rejects_rehashed_noncanonical_company_snapshot():
    work_archive, dossier = _company_archive_and_dossier()
    assessment = dossier.company_assessments[0]
    snapshot = assessment.normalized_evidence
    assert snapshot is not None
    tampered_snapshot = replace(
        snapshot,
        as_of="2026-09-20T16:00:00-04:00",
    )
    tampered_assessment = replace(
        assessment,
        normalized_evidence=tampered_snapshot,
    )
    tampered = _rehash_dossier(
        dossier,
        company_assessments=(tampered_assessment,),
    )

    with pytest.raises(
        ValueError,
        match="inconsistent research company assessment",
    ):
        build_research_dossier_archive_record(
            work_archive,
            tampered,
        )
```

- [ ] **Step 5: Run Task-2 tests and verify RED**

Run:

```bash
pytest -q tests/test_research_execution_archive.py
```

Expected: import/attribute failures for Dossier archive interfaces.

- [ ] **Step 6: Add Dossier archive dataclass and recoverable semantic helper types/imports**

Extend production imports:

```python
from .evidence import SOURCE_PRIORITY
from .hierarchical import HierarchicalLinkageResult
from .linkage import LinkageResult
from .research_execution import (
    CompanyLinkageStatus,
    CompanyResearchAssessment,
    FrozenResearchEvidence,
    HierarchicalLinkageSnapshot,
    NormalizedCompanyField,
    NormalizedCompanySnapshot,
    ResearchDossier,
    ResearchDossierStatus,
    ResearchEvidenceBinding,
    ResearchEvidenceDirection,
    ResearchExecutionClosure,
    ResearchFinding,
    ResearchFindingKind,
    ResearchMode,
    ResearchRequirement,
    ResearchRequirementScope,
    ResearchWorkOrder,
    ResearchWorkOrderPolicy,
    _DOSSIER_LIMITATIONS,
    _build_requirements,
    _linkage_status,
    _normalize_policy,
    _validate_work_order_hash,
)
```

Add:

```python
@dataclass(frozen=True)
class ResearchDossierArchiveRecord:
    schema_version: str
    content_type: str
    producer: str
    source_cycle_as_of: str
    evidence_as_of: str
    work_order_archive: ResearchWorkOrderArchiveRecord
    prior_dossier_archive_record_hash: str | None
    dossier_hash: str
    dossier: ResearchDossier
    archive_record_hash: str
```

- [ ] **Step 7: Implement evidence/finding/linkage/company semantic validators**

```python
def _validate_frozen_evidence(
    binding: ResearchEvidenceBinding,
    *,
    order: ResearchWorkOrder,
    evidence_as_of: datetime,
) -> None:
    evidence = binding.evidence
    _validate_sha256(evidence.source_hash, field_name="research evidence source hash")
    _validate_sha256(evidence.payload_hash, field_name="research evidence payload hash")
    if not evidence.source_ref.strip():
        raise ValueError("invalid research evidence source_ref")
    if evidence.source_type not in SOURCE_PRIORITY:
        raise ValueError("unsupported research evidence source_type")
    if not isinstance(evidence.is_observed_fact, bool):
        raise TypeError("research evidence is_observed_fact must be bool")
    if not isinstance(binding.independent, bool):
        raise TypeError("research evidence independent must be bool")
    if (
        binding.independent
        and (
            evidence.source_type == "radar_model_output"
            or not evidence.is_observed_fact
        )
    ):
        raise ValueError("model or inferred evidence cannot be independent")

    if (
        not binding.dimensions
        or binding.dimensions
        != tuple(sorted(binding.dimensions))
        or len(set(binding.dimensions)) != len(binding.dimensions)
        or any(not value or value != value.strip() for value in binding.dimensions)
    ):
        raise ValueError("invalid research evidence dimensions")

    for value in (
        evidence.observed_at,
        evidence.market_asof,
        evidence.retrieved_at,
    ):
        if value is not None and _parse_utc(value) > evidence_as_of:
            raise ValueError("research evidence exceeds dossier evidence_as_of")

    targets = {target.ticker for target in order.targets}
    if evidence.theme is not None and evidence.theme != order.theme_id:
        raise ValueError("research evidence outside work-order scope")
    if evidence.ticker is not None and evidence.ticker not in targets:
        raise ValueError("research evidence outside work-order scope")
    if evidence.theme is None and evidence.ticker is None:
        raise ValueError("research evidence outside work-order scope")

    if order.research_mode is ResearchMode.THEME_REASSESSMENT:
        if binding.target_ticker is not None or evidence.ticker is not None:
            raise ValueError("research evidence outside work-order scope")
    else:
        if binding.target_ticker not in targets:
            raise ValueError("research evidence outside work-order scope")
        if (
            evidence.ticker is not None
            and evidence.ticker != binding.target_ticker
        ):
            raise ValueError("research evidence target mismatch")


def _validate_simple_linkage(
    linkage: LinkageResult,
    *,
    ticker: str,
) -> None:
    if linkage.ticker != ticker:
        raise ValueError("research linkage ticker mismatch")
    for field_name in (
        "correlation",
        "beta",
        "r2",
        "residual_mean",
        "residual_vol",
        "beta_stability",
        "decoupling_score",
    ):
        value = getattr(linkage, field_name)
        if value is not None and not isfinite(float(value)):
            raise ValueError("research linkage numeric field must be finite")


def _validate_hierarchical_snapshot(
    snapshot: HierarchicalLinkageSnapshot,
    *,
    ticker: str,
) -> None:
    if snapshot.target != ticker:
        raise ValueError("research linkage ticker mismatch")
    for field_name in (
        "theme_correlation",
        "theme_beta",
        "r2",
        "incremental_theme_r2",
        "residual_mean",
        "residual_vol",
    ):
        value = getattr(snapshot, field_name)
        if value is not None and not isfinite(float(value)):
            raise ValueError("research linkage numeric field must be finite")
    if (
        snapshot.coefficients
        != tuple(sorted(snapshot.coefficients))
        or len({name for name, _ in snapshot.coefficients})
        != len(snapshot.coefficients)
        or any(
            not name or not isfinite(float(value))
            for name, value in snapshot.coefficients
        )
    ):
        raise ValueError("invalid research hierarchical linkage coefficients")
    _validate_sha256(
        snapshot.source_payload_hash,
        field_name="hierarchical linkage source payload hash",
    )
    reconstructed = HierarchicalLinkageResult(
        target=snapshot.target,
        status=snapshot.status,
        window=snapshot.window,
        observations=snapshot.observations,
        theme_correlation=snapshot.theme_correlation,
        theme_beta=snapshot.theme_beta,
        r2=snapshot.r2,
        incremental_theme_r2=snapshot.incremental_theme_r2,
        residual_mean=snapshot.residual_mean,
        residual_vol=snapshot.residual_vol,
        circularity_warning=snapshot.circularity_warning,
        missing_controls=snapshot.missing_controls,
        coefficients=dict(snapshot.coefficients),
    )
    if canonical_hash(asdict(reconstructed)) != snapshot.source_payload_hash:
        raise ValueError("hierarchical linkage source payload hash mismatch")
```

Add company/finding validation:

```python
def _expected_company_cautions(
    assessment: CompanyResearchAssessment,
    *,
    order: ResearchWorkOrder,
) -> tuple[str, ...]:
    cautions = []
    if assessment.linkage_status is CompanyLinkageStatus.COVERAGE_PENDING:
        cautions.append("linkage coverage pending")
    elif assessment.linkage_status is CompanyLinkageStatus.CIRCULARITY_WARNING:
        cautions.append("linkage circularity warning")
    if (
        assessment.independent_source_count
        < order.minimum_independent_sources_per_company
    ):
        cautions.append("independent source minimum not met")
    return tuple(cautions)


def _validate_company_assessments(
    dossier: ResearchDossier,
    *,
    order: ResearchWorkOrder,
) -> None:
    if order.research_mode is ResearchMode.THEME_REASSESSMENT:
        if dossier.company_assessments:
            raise ValueError("inconsistent research company assessment")
        return

    targets = tuple(target.ticker for target in order.targets)
    if tuple(item.ticker for item in dossier.company_assessments) != targets:
        raise ValueError("inconsistent research company assessment")

    for assessment in dossier.company_assessments:
        bindings = tuple(
            item
            for item in dossier.evidence_bindings
            if item.target_ticker == assessment.ticker
        )
        expected_hashes = tuple(
            sorted(item.evidence.source_hash for item in bindings)
        )
        independent_refs = {
            item.evidence.source_ref
            for item in bindings
            if item.independent
        }
        if (
            assessment.evidence_source_hashes != expected_hashes
            or assessment.independent_source_count != len(independent_refs)
        ):
            raise ValueError("inconsistent research company assessment")

        snapshot = assessment.normalized_evidence
        if snapshot is None:
            expected_dimensions = ()
        else:
            if (
                snapshot.ticker != assessment.ticker
                or snapshot.adapter_name != order.evidence_adapter
            ):
                raise ValueError("inconsistent research company assessment")
            _validate_sha256(
                snapshot.normalized_payload_hash,
                field_name="normalized company payload hash",
            )
            normalized_as_of = _parse_utc(snapshot.as_of)
            if (
                normalized_as_of.isoformat() != snapshot.as_of
                or normalized_as_of < _parse_utc(order.source_cycle_as_of)
                or normalized_as_of > _parse_utc(dossier.evidence_as_of)
                or not snapshot.source_coverage
            ):
                raise ValueError("inconsistent research company assessment")
            all_evidence_hashes = {
                item.evidence.source_hash
                for item in dossier.evidence_bindings
            }
            if (
                snapshot.provenance != tuple(sorted(snapshot.provenance))
                or len(set(snapshot.provenance)) != len(snapshot.provenance)
                or any(
                    digest not in all_evidence_hashes
                    for digest in snapshot.provenance
                )
            ):
                raise ValueError("inconsistent research company assessment")
            names = tuple(field.name for field in snapshot.fields)
            if (
                names != tuple(sorted(names))
                or len(set(names)) != len(names)
                or any(not name for name in names)
            ):
                raise ValueError("inconsistent research company assessment")
            for field in snapshot.fields:
                if isinstance(field.value, bool) or not isinstance(
                    field.value,
                    (int, float, str),
                ):
                    raise TypeError("invalid normalized company field value")
                if isinstance(field.value, float) and not isfinite(field.value):
                    raise ValueError("invalid normalized company field value")
            expected_dimensions = names

        if assessment.covered_dimensions != expected_dimensions:
            raise ValueError("inconsistent research company assessment")

        if assessment.linkage is not None:
            _validate_simple_linkage(
                assessment.linkage,
                ticker=assessment.ticker,
            )
        if assessment.hierarchical_linkage is not None:
            _validate_hierarchical_snapshot(
                assessment.hierarchical_linkage,
                ticker=assessment.ticker,
            )
        expected_status = _linkage_status(
            assessment.linkage,
            assessment.hierarchical_linkage,
        )
        if (
            assessment.linkage_status is not expected_status
            or assessment.cautions
            != _expected_company_cautions(assessment, order=order)
        ):
            raise ValueError("inconsistent research company assessment")


def _validate_findings(
    dossier: ResearchDossier,
    *,
    order: ResearchWorkOrder,
) -> None:
    evidence = {
        item.evidence.source_hash: item.evidence
        for item in dossier.evidence_bindings
    }
    if len(evidence) != len(dossier.evidence_bindings):
        raise ValueError("duplicate research evidence source hash")
    if dossier.findings != tuple(
        sorted(dossier.findings, key=lambda item: item.finding_id)
    ):
        raise ValueError("invalid research finding ordering")

    seen = set()
    targets = {target.ticker for target in order.targets}
    for finding in dossier.findings:
        if (
            not finding.finding_id
            or finding.finding_id != finding.finding_id.strip()
            or finding.finding_id in seen
            or not finding.dimension
            or finding.dimension != finding.dimension.strip()
            or not finding.statement
            or finding.statement != finding.statement.strip()
        ):
            raise ValueError("invalid research finding")
        seen.add(finding.finding_id)
        if finding.target_ticker is not None and finding.target_ticker not in targets:
            raise ValueError("invalid research finding")
        if (
            finding.evidence_source_hashes
            != tuple(sorted(finding.evidence_source_hashes))
            or len(set(finding.evidence_source_hashes))
            != len(finding.evidence_source_hashes)
            or any(digest not in evidence for digest in finding.evidence_source_hashes)
        ):
            raise ValueError("invalid research finding evidence")

        if finding.kind is ResearchFindingKind.UNRESOLVED:
            if finding.direction is not None:
                raise ValueError("invalid unresolved research finding")
        else:
            if finding.direction is None or not finding.evidence_source_hashes:
                raise ValueError("invalid research finding")
            if (
                finding.kind is ResearchFindingKind.OBSERVED_SYNTHESIS
                and any(
                    not evidence[digest].is_observed_fact
                    for digest in finding.evidence_source_hashes
                )
            ):
                raise ValueError("invalid observed research finding")

        if finding.target_ticker is not None:
            for digest in finding.evidence_source_hashes:
                evidence_ticker = evidence[digest].ticker
                if evidence_ticker not in (None, finding.target_ticker):
                    raise ValueError("research finding cites another target")
```

- [ ] **Step 8: Implement requirement/status/Dossier hash validation**

```python
def _requirement_satisfied(
    requirement: ResearchRequirement,
    *,
    dossier: ResearchDossier,
    assessment_by_ticker: Mapping[str, CompanyResearchAssessment],
) -> bool:
    if requirement.scope is ResearchRequirementScope.THEME_EVIDENCE:
        return any(
            item.target_ticker is None
            and requirement.dimension in item.dimensions
            for item in dossier.evidence_bindings
        )

    target = requirement.target_ticker
    if target is None:
        return False
    assessment = assessment_by_ticker[target]
    if requirement.scope is ResearchRequirementScope.COMPANY_LINKAGE:
        return assessment.linkage_status is CompanyLinkageStatus.USABLE

    return (
        any(
            item.target_ticker == target
            and requirement.dimension in item.dimensions
            for item in dossier.evidence_bindings
        )
        and assessment.normalized_evidence is not None
        and requirement.dimension in assessment.covered_dimensions
    )


def _expected_dossier_status(
    dossier: ResearchDossier,
    *,
    order: ResearchWorkOrder,
) -> ResearchDossierStatus:
    assessment_by_ticker = {
        item.ticker: item for item in dossier.company_assessments
    }
    unsatisfied = tuple(
        item
        for item in order.requirements
        if not _requirement_satisfied(
            item,
            dossier=dossier,
            assessment_by_ticker=assessment_by_ticker,
        )
    )
    independent_refs = {
        item.evidence.source_ref
        for item in dossier.evidence_bindings
        if item.independent
    }
    company_complete = (
        order.research_mode is ResearchMode.THEME_REASSESSMENT
        or all(
            item.normalized_evidence is not None
            and item.independent_source_count
            >= order.minimum_independent_sources_per_company
            for item in dossier.company_assessments
        )
    )
    complete = (
        not unsatisfied
        and len(independent_refs) >= order.minimum_independent_sources
        and company_complete
    )
    if complete:
        return ResearchDossierStatus.COMPLETE
    if dossier.closure is ResearchExecutionClosure.CLOSED:
        return ResearchDossierStatus.BLOCKED_INSUFFICIENT_EVIDENCE

    has_activity = bool(dossier.evidence_bindings or dossier.findings)
    has_activity = has_activity or any(
        item.normalized_evidence is not None
        or item.linkage_status is not CompanyLinkageStatus.NOT_PROVIDED
        for item in dossier.company_assessments
    )
    return (
        ResearchDossierStatus.PARTIAL
        if has_activity
        else ResearchDossierStatus.NOT_STARTED
    )


def _dossier_payload_without_hash(
    dossier: ResearchDossier,
) -> dict[str, object]:
    payload = asdict(dossier)
    payload.pop("dossier_hash")
    return payload


def _validate_dossier(
    dossier: ResearchDossier,
    *,
    order: ResearchWorkOrder,
) -> None:
    if (
        dossier.schema_version != "0.1"
        or dossier.work_order_hash != order.work_order_hash
        or dossier.source_archive_record_hash
        != order.source_archive_record_hash
        or dossier.source_cycle_as_of != order.source_cycle_as_of
        or dossier.theme_id != order.theme_id
        or dossier.research_mode is not order.research_mode
        or tuple(dossier.limitations) != tuple(_DOSSIER_LIMITATIONS)
    ):
        raise ValueError("research dossier work-order lineage mismatch")

    _validate_sha256(dossier.input_hash, field_name="research dossier input hash")
    _validate_sha256(dossier.dossier_hash, field_name="research dossier hash")
    evidence_as_of = _parse_utc(dossier.evidence_as_of)
    if evidence_as_of.isoformat() != dossier.evidence_as_of:
        raise ValueError("research dossier evidence_as_of must be canonical UTC")
    if evidence_as_of < _parse_utc(dossier.source_cycle_as_of):
        raise ValueError("research dossier evidence_as_of precedes source cycle")

    if dossier.evidence_bindings != tuple(
        sorted(
            dossier.evidence_bindings,
            key=lambda item: (
                item.evidence.source_hash,
                item.target_ticker or "",
                item.direction.value,
                item.dimensions,
            ),
        )
    ):
        raise ValueError("invalid research evidence binding ordering")
    for binding in dossier.evidence_bindings:
        _validate_frozen_evidence(
            binding,
            order=order,
            evidence_as_of=evidence_as_of,
        )

    _validate_company_assessments(dossier, order=order)
    _validate_findings(dossier, order=order)

    assessment_by_ticker = {
        item.ticker: item for item in dossier.company_assessments
    }
    satisfied = tuple(
        item
        for item in order.requirements
        if _requirement_satisfied(
            item,
            dossier=dossier,
            assessment_by_ticker=assessment_by_ticker,
        )
    )
    satisfied_set = set(satisfied)
    unsatisfied = tuple(
        item for item in order.requirements if item not in satisfied_set
    )
    if (
        dossier.satisfied_requirements != satisfied
        or dossier.unsatisfied_requirements != unsatisfied
    ):
        raise ValueError("inconsistent research requirement partition")

    independent_refs = {
        item.evidence.source_ref
        for item in dossier.evidence_bindings
        if item.independent
    }
    if dossier.independent_source_count != len(independent_refs):
        raise ValueError("inconsistent research independent-source count")

    expected_contradiction = any(
        item.direction is ResearchEvidenceDirection.CONTRADICTING
        for item in dossier.evidence_bindings
    ) or any(
        item.kind is not ResearchFindingKind.UNRESOLVED
        and item.direction is ResearchEvidenceDirection.CONTRADICTING
        for item in dossier.findings
    )
    expected_unresolved = any(
        item.kind is ResearchFindingKind.UNRESOLVED
        for item in dossier.findings
    )
    if (
        dossier.contradictions_present != expected_contradiction
        or dossier.unresolved_present != expected_unresolved
        or dossier.status is not _expected_dossier_status(dossier, order=order)
    ):
        raise ValueError("inconsistent research dossier derived state")

    if canonical_hash(_dossier_payload_without_hash(dossier)) != dossier.dossier_hash:
        raise ValueError("research dossier hash mismatch")
```

- [ ] **Step 9: Implement Dossier archive builder/validator/path**

```python
def _dossier_archive_payload_without_hash(
    record: ResearchDossierArchiveRecord,
) -> dict[str, object]:
    payload = asdict(record)
    payload.pop("archive_record_hash")
    return payload


def _validate_dossier_archive_record(
    record: ResearchDossierArchiveRecord,
) -> None:
    if (
        record.schema_version != SCHEMA_VERSION
        or record.content_type != DOSSIER_CONTENT_TYPE
        or record.producer != PRODUCER
    ):
        raise ValueError("unsupported research dossier archive contract")
    _validate_work_order_archive_record(record.work_order_archive)
    for field_name, value in (
        ("research dossier hash", record.dossier_hash),
        ("research dossier archive hash", record.archive_record_hash),
    ):
        _validate_sha256(value, field_name=field_name)
    if record.prior_dossier_archive_record_hash is not None:
        _validate_sha256(
            record.prior_dossier_archive_record_hash,
            field_name="prior research dossier archive hash",
        )

    if (
        record.source_cycle_as_of != record.dossier.source_cycle_as_of
        or record.evidence_as_of != record.dossier.evidence_as_of
        or record.dossier_hash != record.dossier.dossier_hash
    ):
        raise ValueError("research dossier archive nested identity mismatch")

    order = record.work_order_archive.work_order
    _validate_dossier(record.dossier, order=order)
    if (
        record.dossier.work_order_hash
        != record.work_order_archive.work_order_hash
        or record.dossier.source_archive_record_hash
        != record.work_order_archive.source_replay_archive_record_hash
        or record.dossier.source_cycle_as_of
        != record.work_order_archive.source_cycle_as_of
        or record.dossier.theme_id != order.theme_id
        or record.dossier.research_mode is not order.research_mode
    ):
        raise ValueError("research dossier work-order lineage mismatch")

    if canonical_hash(_dossier_archive_payload_without_hash(record)) != record.archive_record_hash:
        raise ValueError("research dossier archive hash mismatch")


def build_research_dossier_archive_record(
    work_order_archive: ResearchWorkOrderArchiveRecord,
    dossier: ResearchDossier,
    *,
    prior_dossier_archive: ResearchDossierArchiveRecord | None = None,
) -> ResearchDossierArchiveRecord:
    _validate_work_order_archive_record(work_order_archive)
    _validate_dossier(
        dossier,
        order=work_order_archive.work_order,
    )

    prior_hash = None
    if prior_dossier_archive is not None:
        _validate_dossier_archive_record(prior_dossier_archive)
        if prior_dossier_archive.work_order_archive != work_order_archive:
            raise ValueError("research dossier parent work order mismatch")
        if (
            _parse_utc(dossier.evidence_as_of)
            <= _parse_utc(prior_dossier_archive.evidence_as_of)
        ):
            raise ValueError("research dossier parent must be strictly earlier")
        prior_hash = prior_dossier_archive.archive_record_hash

    seed = ResearchDossierArchiveRecord(
        schema_version=SCHEMA_VERSION,
        content_type=DOSSIER_CONTENT_TYPE,
        producer=PRODUCER,
        source_cycle_as_of=dossier.source_cycle_as_of,
        evidence_as_of=dossier.evidence_as_of,
        work_order_archive=work_order_archive,
        prior_dossier_archive_record_hash=prior_hash,
        dossier_hash=dossier.dossier_hash,
        dossier=dossier,
        archive_record_hash="0" * 64,
    )
    record = replace(
        seed,
        archive_record_hash=canonical_hash(
            _dossier_archive_payload_without_hash(seed)
        ),
    )
    _validate_dossier_archive_record(record)
    return record


def research_dossier_archive_path(
    record: ResearchDossierArchiveRecord,
    archive_root: str | Path,
) -> Path:
    return (
        Path(archive_root)
        / "dossiers"
        / _cycle_date(record.source_cycle_as_of)
        / record.work_order_archive.work_order_hash
        / f"{record.archive_record_hash}.json"
    )
```

- [ ] **Step 10: Run Task-2 tests and full regression**

Run:

```bash
pytest -q tests/test_research_execution_archive.py
pytest -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/decision_lab/research_execution_archive.py tests/test_research_execution_archive.py
git commit -m "feat: add immutable research dossier archives"
```

---

### Task 3: Strict typed JSON decoding, standalone read/verify, path identity, and semantic-tamper rejection

**Files:**
- Modify: `src/decision_lab/research_execution_archive.py`
- Modify: `tests/test_research_execution_archive.py`

**Interfaces:**
- Produces:
  - `read_research_work_order_archive`
  - `read_research_dossier_archive`
  - `verify_research_work_order_archive`
  - `verify_research_dossier_archive`
  - exact nested decoders for WorkOrder policy/order/Dossier snapshots.
- Consumes Task-1/2 semantic validators.

- [ ] **Step 1: Add RED round-trip reader tests using direct deterministic JSON helper**

Add test imports:

```python
import json

from decision_lab.research_execution_archive import (
    read_research_dossier_archive,
    read_research_work_order_archive,
    verify_research_dossier_archive,
    verify_research_work_order_archive,
)
```

Add test-only serializer:

```python
def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            asdict(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
```

Add:

```python
def test_work_order_reader_round_trip_preserves_typed_policy_and_order(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    path = research_work_order_archive_path(record, tmp_path)
    _write_json(path, record)

    loaded = read_research_work_order_archive(path)

    assert loaded == record
    assert loaded.work_order_policy == record.work_order_policy
    assert verify_research_work_order_archive(path)


def test_dossier_reader_round_trip_preserves_parent_hash_without_parent_file(tmp_path):
    work_archive, order = _theme_work_order_archive()
    parent = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
        ),
    )
    child = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-21T20:00:00+00:00",
        ),
        prior_dossier_archive=parent,
    )
    path = research_dossier_archive_path(child, tmp_path)
    _write_json(path, child)

    loaded = read_research_dossier_archive(path)

    assert loaded == child
    assert loaded.prior_dossier_archive_record_hash == parent.archive_record_hash
    assert verify_research_dossier_archive(path)
```

- [ ] **Step 2: Add RED strict-schema/path/non-finite tests**

```python
@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.update(extra_field=True),
        lambda payload: payload.pop("producer"),
        lambda payload: payload.__setitem__("archive_record_hash", "0" * 64),
    ],
)
def test_work_order_reader_rejects_top_level_schema_or_hash_tamper(
    tmp_path,
    mutator,
):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    payload = asdict(record)
    mutator(payload)
    path = research_work_order_archive_path(record, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert not verify_research_work_order_archive(path)
    with pytest.raises((TypeError, ValueError)):
        read_research_work_order_archive(path)


def test_work_order_reader_rejects_wrong_filename(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    path = (
        tmp_path
        / "work_orders"
        / "2026-09-19"
        / f"{'1' * 64}.json"
    )
    _write_json(path, record)

    with pytest.raises(
        ValueError,
        match="research work-order archive filename mismatch",
    ):
        read_research_work_order_archive(path)


def test_dossier_reader_rejects_wrong_work_order_directory_and_filename(tmp_path):
    work_archive, order = _theme_work_order_archive()
    record = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
        ),
    )
    wrong_dir = (
        tmp_path
        / "dossiers"
        / "2026-09-19"
        / ("1" * 64)
        / f"{record.archive_record_hash}.json"
    )
    _write_json(wrong_dir, record)
    with pytest.raises(
        ValueError,
        match="research dossier work-order directory mismatch",
    ):
        read_research_dossier_archive(wrong_dir)

    wrong_name = (
        tmp_path
        / "dossiers"
        / "2026-09-19"
        / record.work_order_archive.work_order_hash
        / f"{'2' * 64}.json"
    )
    _write_json(wrong_name, record)
    with pytest.raises(
        ValueError,
        match="research dossier archive filename mismatch",
    ):
        read_research_dossier_archive(wrong_name)


def test_reader_rejects_non_finite_json_constant(tmp_path):
    work_archive, dossier = _company_archive_and_dossier()
    record = build_research_dossier_archive_record(
        work_archive,
        dossier,
    )
    payload = asdict(record)
    payload["dossier"]["company_assessments"][0]["linkage"]["beta"] = float("nan")
    path = research_dossier_archive_path(record, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, allow_nan=True),
        encoding="utf-8",
    )

    assert not verify_research_dossier_archive(path)
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        read_research_dossier_archive(path)
```

- [ ] **Step 3: Add RED nested semantic-tamper reader tests**

```python
def _rehash_archive_payload(payload):
    archive_payload = dict(payload)
    archive_payload["archive_record_hash"] = "0" * 64
    semantic = dict(archive_payload)
    semantic.pop("archive_record_hash")
    archive_payload["archive_record_hash"] = canonical_hash(semantic)
    return archive_payload


def test_reader_rejects_rehashed_false_dossier_status(tmp_path):
    work_archive, dossier = _company_archive_and_dossier()
    record = build_research_dossier_archive_record(
        work_archive,
        dossier,
    )
    payload = asdict(record)
    payload["dossier"]["status"] = "PARTIAL"
    nested = dict(payload["dossier"])
    nested["dossier_hash"] = "0" * 64
    semantic = dict(nested)
    semantic.pop("dossier_hash")
    nested["dossier_hash"] = canonical_hash(semantic)
    payload["dossier"] = nested
    payload["dossier_hash"] = nested["dossier_hash"]
    payload = _rehash_archive_payload(payload)
    path = (
        tmp_path
        / "dossiers"
        / "2026-09-19"
        / work_archive.work_order_hash
        / f"{payload['archive_record_hash']}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="inconsistent research dossier derived state",
    ):
        read_research_dossier_archive(path)
```

- [ ] **Step 4: Run Task-3 tests and verify RED**

Run:

```bash
pytest -q tests/test_research_execution_archive.py
```

Expected: read/verify imports or decoding paths fail.

- [ ] **Step 5: Implement strict primitive helpers and exact field sets**

Add `json` import and constants:

```python
import json

_WORK_ORDER_POLICY_FIELDS = {
    "version",
    "theme_reassessment_dimensions",
    "industrials_company_dimensions",
    "biotech_company_dimensions",
    "minimum_independent_sources",
    "minimum_independent_sources_per_company",
    "require_usable_linkage_for_company",
}
_RESEARCH_TARGET_FIELDS = {
    "ticker",
    "layer",
    "membership_state",
    "expression_role",
    "effective_from",
    "effective_to",
    "provenance",
}
_RESEARCH_REQUIREMENT_FIELDS = {
    "scope",
    "dimension",
    "target_ticker",
}
_RESEARCH_WORK_ORDER_FIELDS = {
    "schema_version",
    "source_archive_record_hash",
    "source_replay_result_hash",
    "source_cycle_as_of",
    "theme_id",
    "source_routing_intent",
    "source_registered",
    "source_allocated_tier",
    "source_forced_review",
    "authorization",
    "research_mode",
    "evidence_adapter",
    "package_version",
    "universe_version",
    "package_lineage_exactly_recoverable",
    "targets",
    "requirements",
    "minimum_independent_sources",
    "minimum_independent_sources_per_company",
    "contradiction_questions",
    "policy_hash",
    "work_order_hash",
}
_WORK_ORDER_ARCHIVE_FIELDS = {
    "schema_version",
    "content_type",
    "producer",
    "source_cycle_as_of",
    "source_replay_archive_record_hash",
    "source_replay_result_hash",
    "work_order_hash",
    "work_order_policy",
    "work_order",
    "archive_record_hash",
}
_FROZEN_EVIDENCE_FIELDS = {
    "evidence_id",
    "source_hash",
    "payload_hash",
    "observed_at",
    "retrieved_at",
    "market_asof",
    "ticker",
    "theme",
    "source_type",
    "source_ref",
    "fact_type",
    "is_observed_fact",
    "model_version",
    "notes",
}
_EVIDENCE_BINDING_FIELDS = {
    "evidence",
    "independent",
    "direction",
    "dimensions",
    "target_ticker",
}
_NORMALIZED_FIELD_FIELDS = {"name", "value"}
_NORMALIZED_SNAPSHOT_FIELDS = {
    "ticker",
    "as_of",
    "adapter_name",
    "source_coverage",
    "provenance",
    "fields",
    "normalized_payload_hash",
}
_LINKAGE_RESULT_FIELDS = {
    "ticker",
    "control_name",
    "window",
    "correlation",
    "beta",
    "r2",
    "residual_mean",
    "residual_vol",
    "beta_stability",
    "decoupling_score",
    "circularity_warning",
    "observations",
}
_HIERARCHICAL_SNAPSHOT_FIELDS = {
    "target",
    "status",
    "window",
    "observations",
    "theme_correlation",
    "theme_beta",
    "r2",
    "incremental_theme_r2",
    "residual_mean",
    "residual_vol",
    "circularity_warning",
    "missing_controls",
    "coefficients",
    "source_payload_hash",
}
_COMPANY_ASSESSMENT_FIELDS = {
    "ticker",
    "normalized_evidence",
    "evidence_source_hashes",
    "independent_source_count",
    "covered_dimensions",
    "linkage_status",
    "linkage",
    "hierarchical_linkage",
    "cautions",
}
_RESEARCH_FINDING_FIELDS = {
    "finding_id",
    "kind",
    "direction",
    "dimension",
    "target_ticker",
    "statement",
    "evidence_source_hashes",
}
_RESEARCH_DOSSIER_FIELDS = {
    "schema_version",
    "work_order_hash",
    "source_archive_record_hash",
    "source_cycle_as_of",
    "theme_id",
    "research_mode",
    "evidence_as_of",
    "closure",
    "status",
    "evidence_bindings",
    "independent_source_count",
    "satisfied_requirements",
    "unsatisfied_requirements",
    "company_assessments",
    "findings",
    "contradictions_present",
    "unresolved_present",
    "limitations",
    "input_hash",
    "dossier_hash",
}
_DOSSIER_ARCHIVE_FIELDS = {
    "schema_version",
    "content_type",
    "producer",
    "source_cycle_as_of",
    "evidence_as_of",
    "work_order_archive",
    "prior_dossier_archive_record_hash",
    "dossier_hash",
    "dossier",
    "archive_record_hash",
}
```

Add helpers:

```python
def _require_mapping(value, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a JSON object")
    return value


def _require_exact_fields(
    payload: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{label} fields mismatch: "
            f"missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )


def _require_list(value, *, field_name: str) -> list:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a JSON array")
    return value


def _require_str(value, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    return value


def _require_optional_str(value, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name=field_name)


def _require_bool(value, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be bool")
    return value


def _require_int(value, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int")
    return value


def _require_number_or_none(value, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric or null")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    return numeric


def _tuple_of_strings(value, *, field_name: str) -> tuple[str, ...]:
    return tuple(
        _require_str(item, field_name=field_name)
        for item in _require_list(value, field_name=field_name)
    )


def _reject_json_constant(value: str):
    raise ValueError(f"non-finite JSON constant: {value}")
```

- [ ] **Step 6: Implement WorkOrder policy/order/archive decoders**

Import:

```python
from .replay_cohort import RoutingIntent
from .research_budget import ResearchTier
from .research_execution import (
    ResearchAuthorization,
    ResearchTarget,
)
```

Add:

```python
def _decode_work_order_policy(value) -> ResearchWorkOrderPolicy:
    payload = _require_mapping(value, label="ResearchWorkOrderPolicy")
    _require_exact_fields(
        payload,
        _WORK_ORDER_POLICY_FIELDS,
        label="ResearchWorkOrderPolicy",
    )
    return ResearchWorkOrderPolicy(
        version=_require_str(payload["version"], field_name="version"),
        theme_reassessment_dimensions=_tuple_of_strings(
            payload["theme_reassessment_dimensions"],
            field_name="theme_reassessment_dimensions",
        ),
        industrials_company_dimensions=_tuple_of_strings(
            payload["industrials_company_dimensions"],
            field_name="industrials_company_dimensions",
        ),
        biotech_company_dimensions=_tuple_of_strings(
            payload["biotech_company_dimensions"],
            field_name="biotech_company_dimensions",
        ),
        minimum_independent_sources=_require_int(
            payload["minimum_independent_sources"],
            field_name="minimum_independent_sources",
        ),
        minimum_independent_sources_per_company=_require_int(
            payload["minimum_independent_sources_per_company"],
            field_name="minimum_independent_sources_per_company",
        ),
        require_usable_linkage_for_company=_require_bool(
            payload["require_usable_linkage_for_company"],
            field_name="require_usable_linkage_for_company",
        ),
    )


def _decode_target(value) -> ResearchTarget:
    payload = _require_mapping(value, label="ResearchTarget")
    _require_exact_fields(payload, _RESEARCH_TARGET_FIELDS, label="ResearchTarget")
    return ResearchTarget(
        ticker=_require_str(payload["ticker"], field_name="ticker"),
        layer=_require_str(payload["layer"], field_name="layer"),
        membership_state=_require_str(
            payload["membership_state"],
            field_name="membership_state",
        ),
        expression_role=_require_str(
            payload["expression_role"],
            field_name="expression_role",
        ),
        effective_from=_require_optional_str(
            payload["effective_from"],
            field_name="effective_from",
        ),
        effective_to=_require_optional_str(
            payload["effective_to"],
            field_name="effective_to",
        ),
        provenance=_tuple_of_strings(
            payload["provenance"],
            field_name="provenance",
        ),
    )


def _decode_requirement(value) -> ResearchRequirement:
    payload = _require_mapping(value, label="ResearchRequirement")
    _require_exact_fields(
        payload,
        _RESEARCH_REQUIREMENT_FIELDS,
        label="ResearchRequirement",
    )
    return ResearchRequirement(
        scope=ResearchRequirementScope(
            _require_str(payload["scope"], field_name="scope")
        ),
        dimension=_require_str(payload["dimension"], field_name="dimension"),
        target_ticker=_require_optional_str(
            payload["target_ticker"],
            field_name="target_ticker",
        ),
    )


def _decode_work_order(value) -> ResearchWorkOrder:
    payload = _require_mapping(value, label="ResearchWorkOrder")
    _require_exact_fields(
        payload,
        _RESEARCH_WORK_ORDER_FIELDS,
        label="ResearchWorkOrder",
    )
    return ResearchWorkOrder(
        schema_version=_require_str(payload["schema_version"], field_name="schema_version"),
        source_archive_record_hash=_require_str(
            payload["source_archive_record_hash"],
            field_name="source_archive_record_hash",
        ),
        source_replay_result_hash=_require_str(
            payload["source_replay_result_hash"],
            field_name="source_replay_result_hash",
        ),
        source_cycle_as_of=_require_str(
            payload["source_cycle_as_of"],
            field_name="source_cycle_as_of",
        ),
        theme_id=_require_str(payload["theme_id"], field_name="theme_id"),
        source_routing_intent=RoutingIntent(
            _require_str(payload["source_routing_intent"], field_name="source_routing_intent")
        ),
        source_registered=_require_bool(
            payload["source_registered"],
            field_name="source_registered",
        ),
        source_allocated_tier=ResearchTier(
            _require_str(payload["source_allocated_tier"], field_name="source_allocated_tier")
        ),
        source_forced_review=_require_bool(
            payload["source_forced_review"],
            field_name="source_forced_review",
        ),
        authorization=ResearchAuthorization(
            _require_str(payload["authorization"], field_name="authorization")
        ),
        research_mode=ResearchMode(
            _require_str(payload["research_mode"], field_name="research_mode")
        ),
        evidence_adapter=_require_optional_str(
            payload["evidence_adapter"],
            field_name="evidence_adapter",
        ),
        package_version=_require_optional_str(
            payload["package_version"],
            field_name="package_version",
        ),
        universe_version=_require_optional_str(
            payload["universe_version"],
            field_name="universe_version",
        ),
        package_lineage_exactly_recoverable=_require_bool(
            payload["package_lineage_exactly_recoverable"],
            field_name="package_lineage_exactly_recoverable",
        ),
        targets=tuple(
            _decode_target(item)
            for item in _require_list(payload["targets"], field_name="targets")
        ),
        requirements=tuple(
            _decode_requirement(item)
            for item in _require_list(payload["requirements"], field_name="requirements")
        ),
        minimum_independent_sources=_require_int(
            payload["minimum_independent_sources"],
            field_name="minimum_independent_sources",
        ),
        minimum_independent_sources_per_company=_require_int(
            payload["minimum_independent_sources_per_company"],
            field_name="minimum_independent_sources_per_company",
        ),
        contradiction_questions=_tuple_of_strings(
            payload["contradiction_questions"],
            field_name="contradiction_questions",
        ),
        policy_hash=_require_str(payload["policy_hash"], field_name="policy_hash"),
        work_order_hash=_require_str(
            payload["work_order_hash"],
            field_name="work_order_hash",
        ),
    )


def _decode_work_order_archive(value) -> ResearchWorkOrderArchiveRecord:
    payload = _require_mapping(value, label="ResearchWorkOrderArchiveRecord")
    _require_exact_fields(
        payload,
        _WORK_ORDER_ARCHIVE_FIELDS,
        label="ResearchWorkOrderArchiveRecord",
    )
    record = ResearchWorkOrderArchiveRecord(
        schema_version=_require_str(payload["schema_version"], field_name="schema_version"),
        content_type=_require_str(payload["content_type"], field_name="content_type"),
        producer=_require_str(payload["producer"], field_name="producer"),
        source_cycle_as_of=_require_str(
            payload["source_cycle_as_of"],
            field_name="source_cycle_as_of",
        ),
        source_replay_archive_record_hash=_require_str(
            payload["source_replay_archive_record_hash"],
            field_name="source_replay_archive_record_hash",
        ),
        source_replay_result_hash=_require_str(
            payload["source_replay_result_hash"],
            field_name="source_replay_result_hash",
        ),
        work_order_hash=_require_str(
            payload["work_order_hash"],
            field_name="work_order_hash",
        ),
        work_order_policy=_decode_work_order_policy(payload["work_order_policy"]),
        work_order=_decode_work_order(payload["work_order"]),
        archive_record_hash=_require_str(
            payload["archive_record_hash"],
            field_name="archive_record_hash",
        ),
    )
    _validate_work_order_archive_record(record)
    return record
```

- [ ] **Step 7: Implement Dossier nested decoders**

Add exact decoders for immutable snapshots:

```python
def _decode_frozen_evidence(value) -> FrozenResearchEvidence:
    payload = _require_mapping(value, label="FrozenResearchEvidence")
    _require_exact_fields(payload, _FROZEN_EVIDENCE_FIELDS, label="FrozenResearchEvidence")
    return FrozenResearchEvidence(
        evidence_id=_require_str(payload["evidence_id"], field_name="evidence_id"),
        source_hash=_require_str(payload["source_hash"], field_name="source_hash"),
        payload_hash=_require_str(payload["payload_hash"], field_name="payload_hash"),
        observed_at=_require_str(payload["observed_at"], field_name="observed_at"),
        retrieved_at=_require_optional_str(payload["retrieved_at"], field_name="retrieved_at"),
        market_asof=_require_optional_str(payload["market_asof"], field_name="market_asof"),
        ticker=_require_optional_str(payload["ticker"], field_name="ticker"),
        theme=_require_optional_str(payload["theme"], field_name="theme"),
        source_type=_require_str(payload["source_type"], field_name="source_type"),
        source_ref=_require_str(payload["source_ref"], field_name="source_ref"),
        fact_type=_require_str(payload["fact_type"], field_name="fact_type"),
        is_observed_fact=_require_bool(
            payload["is_observed_fact"],
            field_name="is_observed_fact",
        ),
        model_version=_require_optional_str(payload["model_version"], field_name="model_version"),
        notes=_require_optional_str(payload["notes"], field_name="notes"),
    )


def _decode_evidence_binding(value) -> ResearchEvidenceBinding:
    payload = _require_mapping(value, label="ResearchEvidenceBinding")
    _require_exact_fields(payload, _EVIDENCE_BINDING_FIELDS, label="ResearchEvidenceBinding")
    return ResearchEvidenceBinding(
        evidence=_decode_frozen_evidence(payload["evidence"]),
        independent=_require_bool(payload["independent"], field_name="independent"),
        direction=ResearchEvidenceDirection(
            _require_str(payload["direction"], field_name="direction")
        ),
        dimensions=_tuple_of_strings(payload["dimensions"], field_name="dimensions"),
        target_ticker=_require_optional_str(
            payload["target_ticker"],
            field_name="target_ticker",
        ),
    )


def _decode_normalized_field(value) -> NormalizedCompanyField:
    payload = _require_mapping(value, label="NormalizedCompanyField")
    _require_exact_fields(payload, _NORMALIZED_FIELD_FIELDS, label="NormalizedCompanyField")
    raw = payload["value"]
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise TypeError("normalized company field value has invalid type")
    if isinstance(raw, float) and not isfinite(raw):
        raise ValueError("normalized company field value must be finite")
    return NormalizedCompanyField(
        name=_require_str(payload["name"], field_name="name"),
        value=raw,
    )


def _decode_normalized_snapshot(value) -> NormalizedCompanySnapshot:
    payload = _require_mapping(value, label="NormalizedCompanySnapshot")
    _require_exact_fields(
        payload,
        _NORMALIZED_SNAPSHOT_FIELDS,
        label="NormalizedCompanySnapshot",
    )
    return NormalizedCompanySnapshot(
        ticker=_require_str(payload["ticker"], field_name="ticker"),
        as_of=_require_str(payload["as_of"], field_name="as_of"),
        adapter_name=_require_str(payload["adapter_name"], field_name="adapter_name"),
        source_coverage=_require_str(payload["source_coverage"], field_name="source_coverage"),
        provenance=_tuple_of_strings(payload["provenance"], field_name="provenance"),
        fields=tuple(
            _decode_normalized_field(item)
            for item in _require_list(payload["fields"], field_name="fields")
        ),
        normalized_payload_hash=_require_str(
            payload["normalized_payload_hash"],
            field_name="normalized_payload_hash",
        ),
    )


def _decode_linkage_result(value) -> LinkageResult:
    payload = _require_mapping(value, label="LinkageResult")
    _require_exact_fields(payload, _LINKAGE_RESULT_FIELDS, label="LinkageResult")
    return LinkageResult(
        ticker=_require_str(payload["ticker"], field_name="ticker"),
        control_name=_require_str(payload["control_name"], field_name="control_name"),
        window=_require_int(payload["window"], field_name="window"),
        correlation=_require_number_or_none(payload["correlation"], field_name="correlation"),
        beta=_require_number_or_none(payload["beta"], field_name="beta"),
        r2=_require_number_or_none(payload["r2"], field_name="r2"),
        residual_mean=_require_number_or_none(payload["residual_mean"], field_name="residual_mean"),
        residual_vol=_require_number_or_none(payload["residual_vol"], field_name="residual_vol"),
        beta_stability=_require_number_or_none(payload["beta_stability"], field_name="beta_stability"),
        decoupling_score=_require_number_or_none(payload["decoupling_score"], field_name="decoupling_score"),
        circularity_warning=_require_bool(
            payload["circularity_warning"],
            field_name="circularity_warning",
        ),
        observations=_require_int(payload["observations"], field_name="observations"),
    )


def _decode_hierarchical_snapshot(value) -> HierarchicalLinkageSnapshot:
    payload = _require_mapping(value, label="HierarchicalLinkageSnapshot")
    _require_exact_fields(
        payload,
        _HIERARCHICAL_SNAPSHOT_FIELDS,
        label="HierarchicalLinkageSnapshot",
    )
    coefficients = []
    for item in _require_list(payload["coefficients"], field_name="coefficients"):
        if not isinstance(item, list) or len(item) != 2:
            raise TypeError("coefficient must be a two-item JSON array")
        name = _require_str(item[0], field_name="coefficient name")
        number = _require_number_or_none(item[1], field_name="coefficient value")
        if number is None:
            raise TypeError("coefficient value must be numeric")
        coefficients.append((name, number))
    return HierarchicalLinkageSnapshot(
        target=_require_str(payload["target"], field_name="target"),
        status=_require_str(payload["status"], field_name="status"),
        window=_require_int(payload["window"], field_name="window"),
        observations=_require_int(payload["observations"], field_name="observations"),
        theme_correlation=_require_number_or_none(
            payload["theme_correlation"],
            field_name="theme_correlation",
        ),
        theme_beta=_require_number_or_none(payload["theme_beta"], field_name="theme_beta"),
        r2=_require_number_or_none(payload["r2"], field_name="r2"),
        incremental_theme_r2=_require_number_or_none(
            payload["incremental_theme_r2"],
            field_name="incremental_theme_r2",
        ),
        residual_mean=_require_number_or_none(
            payload["residual_mean"],
            field_name="residual_mean",
        ),
        residual_vol=_require_number_or_none(
            payload["residual_vol"],
            field_name="residual_vol",
        ),
        circularity_warning=_require_bool(
            payload["circularity_warning"],
            field_name="circularity_warning",
        ),
        missing_controls=_tuple_of_strings(
            payload["missing_controls"],
            field_name="missing_controls",
        ),
        coefficients=tuple(coefficients),
        source_payload_hash=_require_str(
            payload["source_payload_hash"],
            field_name="source_payload_hash",
        ),
    )
```

Then company/finding/Dossier decoders:

```python
def _decode_company_assessment(value) -> CompanyResearchAssessment:
    payload = _require_mapping(value, label="CompanyResearchAssessment")
    _require_exact_fields(
        payload,
        _COMPANY_ASSESSMENT_FIELDS,
        label="CompanyResearchAssessment",
    )
    normalized = payload["normalized_evidence"]
    simple = payload["linkage"]
    hierarchical = payload["hierarchical_linkage"]
    return CompanyResearchAssessment(
        ticker=_require_str(payload["ticker"], field_name="ticker"),
        normalized_evidence=(
            None if normalized is None else _decode_normalized_snapshot(normalized)
        ),
        evidence_source_hashes=_tuple_of_strings(
            payload["evidence_source_hashes"],
            field_name="evidence_source_hashes",
        ),
        independent_source_count=_require_int(
            payload["independent_source_count"],
            field_name="independent_source_count",
        ),
        covered_dimensions=_tuple_of_strings(
            payload["covered_dimensions"],
            field_name="covered_dimensions",
        ),
        linkage_status=CompanyLinkageStatus(
            _require_str(payload["linkage_status"], field_name="linkage_status")
        ),
        linkage=None if simple is None else _decode_linkage_result(simple),
        hierarchical_linkage=(
            None
            if hierarchical is None
            else _decode_hierarchical_snapshot(hierarchical)
        ),
        cautions=_tuple_of_strings(payload["cautions"], field_name="cautions"),
    )


def _decode_finding(value) -> ResearchFinding:
    payload = _require_mapping(value, label="ResearchFinding")
    _require_exact_fields(payload, _RESEARCH_FINDING_FIELDS, label="ResearchFinding")
    direction = payload["direction"]
    return ResearchFinding(
        finding_id=_require_str(payload["finding_id"], field_name="finding_id"),
        kind=ResearchFindingKind(
            _require_str(payload["kind"], field_name="kind")
        ),
        direction=(
            None
            if direction is None
            else ResearchEvidenceDirection(
                _require_str(direction, field_name="direction")
            )
        ),
        dimension=_require_str(payload["dimension"], field_name="dimension"),
        target_ticker=_require_optional_str(
            payload["target_ticker"],
            field_name="target_ticker",
        ),
        statement=_require_str(payload["statement"], field_name="statement"),
        evidence_source_hashes=_tuple_of_strings(
            payload["evidence_source_hashes"],
            field_name="evidence_source_hashes",
        ),
    )


def _decode_dossier(value) -> ResearchDossier:
    payload = _require_mapping(value, label="ResearchDossier")
    _require_exact_fields(payload, _RESEARCH_DOSSIER_FIELDS, label="ResearchDossier")
    return ResearchDossier(
        schema_version=_require_str(payload["schema_version"], field_name="schema_version"),
        work_order_hash=_require_str(payload["work_order_hash"], field_name="work_order_hash"),
        source_archive_record_hash=_require_str(
            payload["source_archive_record_hash"],
            field_name="source_archive_record_hash",
        ),
        source_cycle_as_of=_require_str(
            payload["source_cycle_as_of"],
            field_name="source_cycle_as_of",
        ),
        theme_id=_require_str(payload["theme_id"], field_name="theme_id"),
        research_mode=ResearchMode(
            _require_str(payload["research_mode"], field_name="research_mode")
        ),
        evidence_as_of=_require_str(payload["evidence_as_of"], field_name="evidence_as_of"),
        closure=ResearchExecutionClosure(
            _require_str(payload["closure"], field_name="closure")
        ),
        status=ResearchDossierStatus(
            _require_str(payload["status"], field_name="status")
        ),
        evidence_bindings=tuple(
            _decode_evidence_binding(item)
            for item in _require_list(payload["evidence_bindings"], field_name="evidence_bindings")
        ),
        independent_source_count=_require_int(
            payload["independent_source_count"],
            field_name="independent_source_count",
        ),
        satisfied_requirements=tuple(
            _decode_requirement(item)
            for item in _require_list(
                payload["satisfied_requirements"],
                field_name="satisfied_requirements",
            )
        ),
        unsatisfied_requirements=tuple(
            _decode_requirement(item)
            for item in _require_list(
                payload["unsatisfied_requirements"],
                field_name="unsatisfied_requirements",
            )
        ),
        company_assessments=tuple(
            _decode_company_assessment(item)
            for item in _require_list(
                payload["company_assessments"],
                field_name="company_assessments",
            )
        ),
        findings=tuple(
            _decode_finding(item)
            for item in _require_list(payload["findings"], field_name="findings")
        ),
        contradictions_present=_require_bool(
            payload["contradictions_present"],
            field_name="contradictions_present",
        ),
        unresolved_present=_require_bool(
            payload["unresolved_present"],
            field_name="unresolved_present",
        ),
        limitations=_tuple_of_strings(payload["limitations"], field_name="limitations"),
        input_hash=_require_str(payload["input_hash"], field_name="input_hash"),
        dossier_hash=_require_str(payload["dossier_hash"], field_name="dossier_hash"),
    )


def _decode_dossier_archive(value) -> ResearchDossierArchiveRecord:
    payload = _require_mapping(value, label="ResearchDossierArchiveRecord")
    _require_exact_fields(
        payload,
        _DOSSIER_ARCHIVE_FIELDS,
        label="ResearchDossierArchiveRecord",
    )
    record = ResearchDossierArchiveRecord(
        schema_version=_require_str(payload["schema_version"], field_name="schema_version"),
        content_type=_require_str(payload["content_type"], field_name="content_type"),
        producer=_require_str(payload["producer"], field_name="producer"),
        source_cycle_as_of=_require_str(
            payload["source_cycle_as_of"],
            field_name="source_cycle_as_of",
        ),
        evidence_as_of=_require_str(
            payload["evidence_as_of"],
            field_name="evidence_as_of",
        ),
        work_order_archive=_decode_work_order_archive(
            payload["work_order_archive"]
        ),
        prior_dossier_archive_record_hash=_require_optional_str(
            payload["prior_dossier_archive_record_hash"],
            field_name="prior_dossier_archive_record_hash",
        ),
        dossier_hash=_require_str(payload["dossier_hash"], field_name="dossier_hash"),
        dossier=_decode_dossier(payload["dossier"]),
        archive_record_hash=_require_str(
            payload["archive_record_hash"],
            field_name="archive_record_hash",
        ),
    )
    _validate_dossier_archive_record(record)
    return record
```

- [ ] **Step 8: Implement standalone readers, path validation, and verify helpers**

```python
def _load_json(path: Path):
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_json_constant,
    )


def read_research_work_order_archive(
    path: str | Path,
) -> ResearchWorkOrderArchiveRecord:
    target = Path(path)
    record = _decode_work_order_archive(_load_json(target))
    if target.name != f"{record.work_order_hash}.json":
        raise ValueError("research work-order archive filename mismatch")
    if target.parent.name != _cycle_date(record.source_cycle_as_of):
        raise ValueError("research archive cycle directory mismatch")
    return record


def read_research_dossier_archive(
    path: str | Path,
) -> ResearchDossierArchiveRecord:
    target = Path(path)
    record = _decode_dossier_archive(_load_json(target))
    if target.name != f"{record.archive_record_hash}.json":
        raise ValueError("research dossier archive filename mismatch")
    if target.parent.name != record.work_order_archive.work_order_hash:
        raise ValueError("research dossier work-order directory mismatch")
    if target.parent.parent.name != _cycle_date(record.source_cycle_as_of):
        raise ValueError("research archive cycle directory mismatch")
    return record


def verify_research_work_order_archive(path: str | Path) -> bool:
    try:
        read_research_work_order_archive(path)
    except FileNotFoundError:
        return False
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return True


def verify_research_dossier_archive(path: str | Path) -> bool:
    try:
        read_research_dossier_archive(path)
    except FileNotFoundError:
        return False
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return True
```

- [ ] **Step 9: Run Task-3 tests and full regression**

Run:

```bash
pytest -q tests/test_research_execution_archive.py
pytest -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/decision_lab/research_execution_archive.py tests/test_research_execution_archive.py
git commit -m "feat: read and verify research execution archives"
```

---

### Task 4: Deterministic serialization, destination policy, append-only writers, symlink containment, and public exports

**Files:**
- Modify: `src/decision_lab/research_execution_archive.py`
- Modify: `tests/test_research_execution_archive.py`
- Modify: `src/decision_lab/__init__.py`

**Interfaces:**
- Produces:
  - `write_research_work_order_archive`
  - `write_research_dossier_archive`
  - public export surface from spec.
- Consumes Task-3 readers for idempotence/conflict checks.

- [ ] **Step 1: Add RED public/private destination and idempotent write tests**

Append imports:

```python
from decision_lab.research_execution_archive import (
    ResearchArchiveDestinationVisibility,
    write_research_dossier_archive,
    write_research_work_order_archive,
)
```

Add:

```python
@pytest.mark.parametrize("unsafe", [False, 1, "yes"])
def test_public_research_archive_requires_literal_public_safe(
    tmp_path,
    unsafe,
):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    root = tmp_path / "recomputed" / "research_execution"

    with pytest.raises(
        PermissionError,
        match="public research archive write requires explicit public_safe=True",
    ):
        write_research_work_order_archive(
            record,
            root,
            destination_visibility=ResearchArchiveDestinationVisibility.PUBLIC,
            public_safe=unsafe,
        )

    assert not root.exists()


def test_work_order_write_is_create_once_and_identical_write_is_idempotent(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    root = tmp_path / "recomputed" / "research_execution"

    first = write_research_work_order_archive(
        record,
        root,
        destination_visibility=ResearchArchiveDestinationVisibility.PUBLIC,
        public_safe=True,
    )
    second = write_research_work_order_archive(
        record,
        root,
        destination_visibility=ResearchArchiveDestinationVisibility.PUBLIC,
        public_safe=True,
    )

    assert first.created
    assert not second.created
    assert first.path == second.path
    assert first.content_hash == record.work_order_hash


def test_dossier_write_round_trip_uses_archive_hash_filename(tmp_path):
    work_archive, order = _theme_work_order_archive()
    record = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
        ),
    )
    root = tmp_path / "private-research"

    written = write_research_dossier_archive(
        record,
        root,
        destination_visibility=ResearchArchiveDestinationVisibility.PRIVATE,
    )

    assert written.created
    assert written.path.name == f"{record.archive_record_hash}.json"
    assert read_research_dossier_archive(written.path) == record
```

- [ ] **Step 2: Add RED conflict/invalid-existing/ledger-live/root tests**

```python
def test_existing_invalid_file_is_never_overwritten(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    root = tmp_path / "private"
    path = research_work_order_archive_path(record, root)
    path.parent.mkdir(parents=True)
    original = b'{"different":true}\n'
    path.write_bytes(original)

    with pytest.raises(
        FileExistsError,
        match="research archive path conflict",
    ):
        write_research_work_order_archive(
            record,
            root,
            destination_visibility=ResearchArchiveDestinationVisibility.PRIVATE,
        )

    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "visibility",
    [
        ResearchArchiveDestinationVisibility.PUBLIC,
        ResearchArchiveDestinationVisibility.PRIVATE,
    ],
)
def test_research_archive_rejects_ledger_live(tmp_path, visibility):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    root = tmp_path / "ledger" / "live" / "research"

    with pytest.raises(
        ValueError,
        match="research archives may not be written under ledger/live",
    ):
        write_research_work_order_archive(
            record,
            root,
            destination_visibility=visibility,
            public_safe=True,
        )


def test_public_research_archive_requires_canonical_root(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )

    with pytest.raises(
        ValueError,
        match="public research archives must use recomputed/research_execution",
    ):
        write_research_work_order_archive(
            record,
            tmp_path / "reports" / "research_execution",
            destination_visibility=ResearchArchiveDestinationVisibility.PUBLIC,
            public_safe=True,
        )
```

- [ ] **Step 3: Add RED symlink and deterministic-byte tests**

```python
def test_dossier_work_order_directory_symlink_cannot_escape_root(tmp_path):
    work_archive, order = _theme_work_order_archive()
    record = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
        ),
    )
    root = tmp_path / "recomputed" / "research_execution"
    outside = tmp_path / "outside"
    work_dir = (
        root
        / "dossiers"
        / "2026-09-19"
        / work_archive.work_order_hash
    )
    work_dir.parent.mkdir(parents=True)
    outside.mkdir()
    try:
        work_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unsupported")

    with pytest.raises(
        ValueError,
        match="research archive directory escapes archive root",
    ):
        write_research_dossier_archive(
            record,
            root,
            destination_visibility=ResearchArchiveDestinationVisibility.PUBLIC,
            public_safe=True,
        )

    assert not (outside / f"{record.archive_record_hash}.json").exists()



def test_work_order_cycle_directory_symlink_cannot_escape_root(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    root = tmp_path / "recomputed" / "research_execution"
    outside = tmp_path / "outside"
    cycle_dir = root / "work_orders" / "2026-09-19"
    cycle_dir.parent.mkdir(parents=True)
    outside.mkdir()
    try:
        cycle_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unsupported")

    with pytest.raises(
        ValueError,
        match="research archive directory escapes archive root",
    ):
        write_research_work_order_archive(
            record,
            root,
            destination_visibility=ResearchArchiveDestinationVisibility.PUBLIC,
            public_safe=True,
        )

    assert not (outside / f"{record.work_order_hash}.json").exists()


def test_public_root_symlink_to_noncanonical_destination_is_rejected(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    target = tmp_path / "reports" / "research_execution"
    target.mkdir(parents=True)
    parent = tmp_path / "recomputed"
    parent.mkdir()
    link = parent / "research_execution"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unsupported")

    with pytest.raises(
        ValueError,
        match="public research archives must use recomputed/research_execution",
    ):
        write_research_work_order_archive(
            record,
            link,
            destination_visibility=ResearchArchiveDestinationVisibility.PUBLIC,
            public_safe=True,
        )


def test_existing_archive_file_symlink_is_conflict(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    source = write_research_work_order_archive(
        record,
        tmp_path / "source",
        destination_visibility=ResearchArchiveDestinationVisibility.PRIVATE,
    )
    target_root = tmp_path / "target"
    target = research_work_order_archive_path(record, target_root)
    target.parent.mkdir(parents=True)
    try:
        target.symlink_to(source.path)
    except OSError:
        pytest.skip("symlink creation unsupported")

    with pytest.raises(
        FileExistsError,
        match="research archive path conflict",
    ):
        write_research_work_order_archive(
            record,
            target_root,
            destination_visibility=ResearchArchiveDestinationVisibility.PRIVATE,
        )


def test_identical_records_have_identical_json_bytes_across_roots(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    first = write_research_work_order_archive(
        record,
        tmp_path / "a",
        destination_visibility=ResearchArchiveDestinationVisibility.PRIVATE,
    )
    second = write_research_work_order_archive(
        record,
        tmp_path / "b",
        destination_visibility=ResearchArchiveDestinationVisibility.PRIVATE,
    )

    assert first.path.read_bytes() == second.path.read_bytes()
```

- [ ] **Step 4: Add RED partial-write cleanup test**

```python
def test_partial_new_research_archive_file_is_removed_on_write_failure(
    tmp_path,
    monkeypatch,
):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    root = tmp_path / "private"

    class BrokenWriter:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def write(self, data):
            raise OSError("simulated research archive write failure")

    import os

    real_fdopen = os.fdopen

    def broken_fdopen(fd, mode):
        os.close(fd)
        return BrokenWriter()

    monkeypatch.setattr(os, "fdopen", broken_fdopen)

    with pytest.raises(
        OSError,
        match="simulated research archive write failure",
    ):
        write_research_work_order_archive(
            record,
            root,
            destination_visibility=ResearchArchiveDestinationVisibility.PRIVATE,
        )

    assert not research_work_order_archive_path(record, root).exists()
    monkeypatch.setattr(os, "fdopen", real_fdopen)
```

- [ ] **Step 5: Run Task-4 tests and verify RED**

Run:

```bash
pytest -q tests/test_research_execution_archive.py
```

Expected: writer/export interfaces missing.

- [ ] **Step 6: Implement deterministic payload/serialization and destination policy**

Add imports:

```python
import os
```

Add:

```python
def _record_payload(record) -> dict[str, object]:
    return asdict(record)


def _serialize_record(record) -> bytes:
    return (
        json.dumps(
            _record_payload(record),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _contains_path_sequence(
    parts: tuple[str, ...],
    sequence: tuple[str, ...],
) -> bool:
    width = len(sequence)
    return any(
        tuple(parts[index:index + width]) == sequence
        for index in range(len(parts) - width + 1)
    )


def _validate_destination_policy(
    archive_root: str | Path,
    *,
    destination_visibility: ResearchArchiveDestinationVisibility,
    public_safe: bool,
) -> Path:
    if not isinstance(
        destination_visibility,
        ResearchArchiveDestinationVisibility,
    ):
        raise TypeError("invalid research archive destination visibility")

    resolved = Path(archive_root).expanduser().resolve(strict=False)
    parts = tuple(resolved.parts)
    if _contains_path_sequence(parts, ("ledger", "live")):
        raise ValueError(
            "research archives may not be written under ledger/live"
        )

    if destination_visibility is ResearchArchiveDestinationVisibility.PUBLIC:
        if public_safe is not True:
            raise PermissionError(
                "public research archive write requires explicit public_safe=True"
            )
        if len(parts) < 2 or parts[-2:] != (
            "recomputed",
            "research_execution",
        ):
            raise ValueError(
                "public research archives must use recomputed/research_execution"
            )
    return resolved


def _ensure_parent_within_root(path: Path, root: Path) -> None:
    resolved_parent = path.parent.resolve(strict=False)
    if not resolved_parent.is_relative_to(root):
        raise ValueError(
            "research archive directory escapes archive root"
        )
```

- [ ] **Step 7: Implement one generic exclusive writer and two typed public writers**

```python
def _write_archive_record(
    record,
    path: Path,
    root: Path,
    *,
    reader,
    content_hash: str,
) -> ResearchArchiveWriteResult:
    requested_payload = _record_payload(record)
    requested_bytes = _serialize_record(record)

    _ensure_parent_within_root(path, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_parent_within_root(path, root)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        if path.is_symlink():
            raise FileExistsError(
                "research archive path conflict"
            ) from None
        try:
            existing = reader(path)
        except (
            FileNotFoundError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise FileExistsError(
                "research archive path conflict"
            ) from exc
        if _record_payload(existing) != requested_payload:
            raise FileExistsError(
                "research archive path conflict"
            )
        return ResearchArchiveWriteResult(
            path=path,
            created=False,
            content_hash=content_hash,
            archive_record_hash=record.archive_record_hash,
        )

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(requested_bytes)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    return ResearchArchiveWriteResult(
        path=path,
        created=True,
        content_hash=content_hash,
        archive_record_hash=record.archive_record_hash,
    )


def write_research_work_order_archive(
    record: ResearchWorkOrderArchiveRecord,
    archive_root: str | Path,
    *,
    destination_visibility: ResearchArchiveDestinationVisibility,
    public_safe: bool = False,
) -> ResearchArchiveWriteResult:
    root = _validate_destination_policy(
        archive_root,
        destination_visibility=destination_visibility,
        public_safe=public_safe,
    )
    _validate_work_order_archive_record(record)
    path = research_work_order_archive_path(record, root)
    return _write_archive_record(
        record,
        path,
        root,
        reader=read_research_work_order_archive,
        content_hash=record.work_order_hash,
    )


def write_research_dossier_archive(
    record: ResearchDossierArchiveRecord,
    archive_root: str | Path,
    *,
    destination_visibility: ResearchArchiveDestinationVisibility,
    public_safe: bool = False,
) -> ResearchArchiveWriteResult:
    root = _validate_destination_policy(
        archive_root,
        destination_visibility=destination_visibility,
        public_safe=public_safe,
    )
    _validate_dossier_archive_record(record)
    path = research_dossier_archive_path(record, root)
    return _write_archive_record(
        record,
        path,
        root,
        reader=read_research_dossier_archive,
        content_hash=record.dossier_hash,
    )
```

- [ ] **Step 8: Add public import RED test, then export Increment-9 interfaces**

Add test:

```python
def test_research_execution_archive_interfaces_are_publicly_importable():
    import decision_lab

    for name in (
        "ResearchArchiveDestinationVisibility",
        "ResearchArchiveWriteResult",
        "ResearchWorkOrderArchiveRecord",
        "ResearchDossierArchiveRecord",
        "build_research_work_order_archive_record",
        "build_research_dossier_archive_record",
        "research_work_order_archive_path",
        "research_dossier_archive_path",
        "read_research_work_order_archive",
        "read_research_dossier_archive",
        "verify_research_work_order_archive",
        "verify_research_dossier_archive",
        "write_research_work_order_archive",
        "write_research_dossier_archive",
    ):
        assert getattr(decision_lab, name) is not None
```

Run just this test and verify RED.

Then modify `src/decision_lab/__init__.py` to import/export exactly those 14 symbols, maintaining Ruff import ordering and sorted `__all__`.

- [ ] **Step 9: Run Task-4 tests and full regression**

Run:

```bash
pytest -q tests/test_research_execution_archive.py
pytest -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/decision_lab/research_execution_archive.py src/decision_lab/__init__.py tests/test_research_execution_archive.py
git commit -m "feat: persist research execution archives safely"
```

---

### Task 5: Final acceptance gaps, archive-boundary audit, Ruff, whole-branch review, and exact-final-tree verification

**Files:**
- Verify: `src/decision_lab/research_execution_archive.py`
- Verify: `src/decision_lab/__init__.py`
- Verify: `tests/test_research_execution_archive.py`
- Review-only: all existing domain modules.

**Interfaces:**
- Verification evidence only.

- [ ] **Step 1: Add final RED tests for Review Focus edge cases**

Add:

```python
def test_reader_does_not_require_parent_file_to_exist(tmp_path):
    work_archive, order = _theme_work_order_archive()
    parent = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
        ),
    )
    child = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-21T20:00:00+00:00",
        ),
        prior_dossier_archive=parent,
    )
    path = research_dossier_archive_path(child, tmp_path)
    _write_json(path, child)

    assert read_research_dossier_archive(path) == child


def test_work_order_archive_policy_tuple_order_is_canonicalized():
    replay_archive, order, policy = _replay_archive_and_order()
    reordered = replace(
        policy,
        industrials_company_dimensions=tuple(
            reversed(policy.industrials_company_dimensions)
        ),
    )

    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=reordered,
    )

    assert record.work_order_policy == replace(
        policy,
        industrials_company_dimensions=tuple(
            sorted(policy.industrials_company_dimensions)
        ),
        biotech_company_dimensions=tuple(
            sorted(policy.biotech_company_dimensions)
        ),
        theme_reassessment_dimensions=tuple(
            sorted(policy.theme_reassessment_dimensions)
        ),
    )


def test_reader_rejects_rehashed_false_independent_source_count(tmp_path):
    work_archive, dossier = _company_archive_and_dossier()
    record = build_research_dossier_archive_record(
        work_archive,
        dossier,
    )
    payload = asdict(record)
    payload["dossier"]["independent_source_count"] = 99
    nested = dict(payload["dossier"])
    semantic = dict(nested)
    semantic.pop("dossier_hash")
    nested["dossier_hash"] = canonical_hash(semantic)
    payload["dossier"] = nested
    payload["dossier_hash"] = nested["dossier_hash"]
    payload = _rehash_archive_payload(payload)
    path = (
        tmp_path
        / "dossiers"
        / "2026-09-19"
        / work_archive.work_order_hash
        / f"{payload['archive_record_hash']}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="inconsistent research independent-source count",
    ):
        read_research_dossier_archive(path)


def test_reader_accepts_shape_valid_input_hash_without_claiming_raw_recompute(tmp_path):
    work_archive, dossier = _company_archive_and_dossier()
    replacement_input_hash = "1" * 64
    altered = replace(
        dossier,
        input_hash=replacement_input_hash,
        dossier_hash="0" * 64,
    )
    semantic = asdict(altered)
    semantic.pop("dossier_hash")
    altered = replace(
        altered,
        dossier_hash=canonical_hash(semantic),
    )
    record_seed = ResearchDossierArchiveRecord(
        schema_version="0.1",
        content_type="research_dossier",
        producer="theme-radar-decision-lab/research-execution-archive@0.1",
        source_cycle_as_of=altered.source_cycle_as_of,
        evidence_as_of=altered.evidence_as_of,
        work_order_archive=work_archive,
        prior_dossier_archive_record_hash=None,
        dossier_hash=altered.dossier_hash,
        dossier=altered,
        archive_record_hash="0" * 64,
    )
    payload = asdict(record_seed)
    payload.pop("archive_record_hash")
    record = replace(
        record_seed,
        archive_record_hash=canonical_hash(payload),
    )
    path = research_dossier_archive_path(record, tmp_path)
    _write_json(path, record)

    loaded = read_research_dossier_archive(path)

    assert loaded.dossier.input_hash == replacement_input_hash
```

The last test intentionally pins the documented limitation: archive integrity cannot reconstruct omitted raw execution inputs.

- [ ] **Step 2: Run fresh full regression**

Run:

```bash
pytest -q
```

Expected: all tests PASS.

- [ ] **Step 3: Run changed-files Ruff**

Run:

```bash
python -m ruff check   src/decision_lab/research_execution_archive.py   src/decision_lab/__init__.py   tests/test_research_execution_archive.py
```

Expected: exit 0.

- [ ] **Step 4: Audit forbidden semantic drift and prohibited dependencies**

Verify no diffs to:

```text
src/decision_lab/research_execution.py
src/decision_lab/replay.py
src/decision_lab/replay_archive.py
src/decision_lab/replay_cohort.py
src/decision_lab/scanner.py
src/decision_lab/research_budget.py
src/decision_lab/market_observation.py
src/decision_lab/evidence.py
src/decision_lab/adapters.py
src/decision_lab/linkage.py
src/decision_lab/hierarchical.py
src/decision_lab/tape.py
src/decision_lab/playbooks.py
src/decision_lab/decision.py
src/decision_lab/outcomes.py
src/decision_lab/themes.py
src/decision_lab/universe.py
src/decision_lab/ledger.py
```

Verify no persistent new `.github/workflows` file.

Verify `research_execution_archive.py` contains no imports/calls for:

```text
requests
urllib
httpx
yfinance
alpaca
polygon
socket
random
uuid
datetime.now
time.time
assess_tape_state
route_playbooks
compile_decision
evaluate_forward_outcomes
missed_upside
summarize_decisions
```

Verify archive public dataclass fields contain none of:

```text
research_value
information_gain
decision_gain
utility_gain
roi
accuracy
performance_score
latest_parent
canonical_child
fork_resolution
time_to_complete
```

- [ ] **Step 5: Whole-branch review against Review Focus**

Inspect specifically:

- WorkOrder builder validates the replay archive by rebuilding it before trusting lineage.
- WorkOrder policy is normalized, stored completely, policy-hash checked, minima checked, and requirements regenerated.
- WorkOrder replay lineage checks actual cohort routing state, not only replay hashes.
- WorkOrder top-level duplicate identity fields exactly equal nested WorkOrder fields.
- Dossier builder validates embedded WorkOrder archive before use.
- Parent builder validates the typed parent archive, exact same WorkOrder archive, and strictly increasing normalized evidence time.
- Same Dossier with different parent hashes produces distinct archive hashes and filenames.
- Dossier validator recomputes dossier_hash, requirement partition, independent-source count, company assessments, linkage status/cautions, findings, contradiction/unresolved flags, and status.
- Dossier validator does not pretend to recompute omitted evidence payload hashes or raw execution input_hash provenance.
- Reader does not inspect filesystem for parent existence or latest state.
- Reader rejects unknown/missing fields and NaN/Infinity at every relevant level.
- Dossier filename binds archive_record_hash, not dossier_hash.
- Public root and literal public_safe semantics match the spec.
- Writers validate before filesystem mutation.
- Writers never overwrite invalid/conflicting files.
- Writer partial-failure cleanup deletes only newly created path.
- Directory symlink escape and final-file symlink conflict paths fail closed.
- No graph/index/progression logic appears.

Any Critical/Important finding gets one TDD fix pass:

1. add reproducing RED test;
2. verify RED;
3. implement minimal fix;
4. verify targeted GREEN;
5. run full suite and Ruff.

Record Minor findings without expanding scope.

- [ ] **Step 6: Exact-final-tree verification**

On exact final branch head:

```bash
pytest -q
python -m ruff check   src/decision_lab/research_execution_archive.py   src/decision_lab/__init__.py   tests/test_research_execution_archive.py
```

Record exact pytest count/time and Ruff result.

Confirm final PR changed-file set is exactly:

```text
docs/superpowers/specs/2026-09-22-research-execution-archive-design.md
docs/superpowers/plans/2026-09-22-research-execution-archive.md
src/decision_lab/research_execution_archive.py
src/decision_lab/__init__.py
tests/test_research_execution_archive.py
```

- [ ] **Step 7: Keep branch unmerged**

Present integration options only after exact-final-tree verification. Do not merge until explicit user authorization.
