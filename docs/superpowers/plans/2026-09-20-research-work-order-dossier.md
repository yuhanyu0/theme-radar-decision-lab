# Research Work Order + Deterministic Research Dossier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Add a deterministic research-execution layer that turns eligible historical replay routing into a ResearchWorkOrder and frozen, evidence-traceable ResearchDossier without implying that allocation equals execution or that research completion grants trading permission.

**Architecture:** Create one focused research_execution.py module. Work-order construction validates source replay semantics through the public cohort evaluator, then freezes authorization, package lineage, targets, and requirements. Dossier construction validates/freeze-copies evidence, findings, company normalization, and linkage inputs into immutable snapshots, derives mechanical coverage/status, and hashes the complete semantic result. Existing replay/archive/cohort, evidence/adapters/linkage, Tape/Playbook/Decision, and filesystem semantics remain unchanged.

**Tech Stack:** Python 3.11, dataclasses, Enum, datetime, math, collections, existing canonical_hash, existing company adapters/linkage dataclasses, pytest, Ruff.

**Spec:** docs/superpowers/specs/2026-09-20-research-work-order-dossier-design.md

## Global Constraints

- Allocation != execution != trading permission.
- build_research_work_order and build_research_dossier are pure; no filesystem, network, ambient clock, random state, or provider SDK.
- Source replay semantics are validated through evaluate_replay_cohort((record,), horizons=(1,)).
- COMPANY_DEEP_DIVE is eligible only for ORDINARY_FULL_RESEARCH or registered FORCED_FULL_REVIEW.
- FORCED_REVIEW_UNREGISTERED may create THEME_REASSESSMENT only and must preserve source tier SCAN_ONLY.
- FORCED_REVIEW_CAPACITY_MISSED is not executable in v0.1.
- GenericEvidenceAdapter is not eligible for COMPANY_DEEP_DIVE.
- EvidenceRecord source_hash is independently recomputed; make_evidence is never called.
- Model/inferred evidence cannot be elevated to independent evidence.
- Company raw facts require ticker-specific evidence support.
- Company requirement coverage requires both an evidence binding and a non-None normalized adapter field.
- Required linkage is complete only when linkage status is USABLE.
- COMPLETE means coverage complete, not thesis correctness or bullishness.
- Frozen output must not retain caller-owned mutable payload/raw_facts/coefficients mappings.
- No company score, price outcome, Tape, Playbook, Decision Object, entry/invalidation, sizing, or order execution.
- No new filesystem archive layer in Increment 8.
- Existing replay.py, replay_archive.py, replay_cohort.py, evidence.py, adapters.py, linkage.py, hierarchical.py, Tape/Playbook/Decision/outcomes, theme/universe/ledger behavior must not change.
- Branch remains unmerged until exact-final-tree pytest, changed-files Ruff, and whole-branch review are green.

## Review Focus

1. **Authorization drift:** manually valid-looking replay records must not let SCAN_ONLY, capacity-missed, or unregistered states create company research or pretend to have FULL authorization.
2. **Mutable nested state:** post-build mutation of EvidenceRecord.payload, CompanyResearchSubmission.raw_facts, or HierarchicalLinkageResult.coefficients must not alter dossier equality or hashes.
3. **Evidence laundering:** model/inferred evidence, cross-company evidence, theme-level evidence used as company raw-fact proof, stale source_hash, and future-dated evidence must fail closed.
4. **False completion:** a binding that merely names a company dimension, missing normalized values, insufficient independent sources, pending/circular linkage, or missing target submission must keep the dossier incomplete.
5. **Canonical identity:** target/evidence/submission/linkage/finding input order, timezone spelling, and mapping insertion order must not change semantic identities; NaN/Infinity and malformed timestamps must be rejected.

---

## File map

- Create src/decision_lab/research_execution.py
  - public research enums/dataclasses;
  - policy normalization and work-order construction;
  - evidence validation/freeze snapshots;
  - company adapter dispatch and normalized snapshots;
  - linkage validation/snapshots;
  - finding validation;
  - dossier requirement coverage/status/hash.
- Create tests/test_research_execution.py
  - source routing/authorization tests;
  - package lineage/target tests;
  - evidence hash/time/scope/independence tests;
  - immutable snapshot tests;
  - company adapter/raw-fact/linkage tests;
  - dossier status/determinism tests;
  - real DataCenter/Genomics acceptance.
- Modify src/decision_lab/__init__.py for public exports only.
- Do not modify behavior in any existing domain module.

---

### Task 1: Work-order types, policy canonicalization, authorization, package lineage, targets, and requirements

**Files:**
- Create: src/decision_lab/research_execution.py
- Create: tests/test_research_execution.py

**Interfaces:**
- Consumes:
  - ReplayArchiveRecord
  - evaluate_replay_cohort
  - RoutingIntent
  - ResearchTier
  - ThemePackage
  - canonical_hash
- Produces:
  - ResearchMode
  - ResearchAuthorization
  - ResearchRequirementScope
  - ResearchRequirement
  - ResearchTarget
  - ResearchWorkOrderPolicy
  - ResearchWorkOrder
  - build_research_work_order(...)

- [ ] **Step 1: Write RED work-order fixtures and happy-path tests**

Create tests/test_research_execution.py with imports and deterministic helpers:

~~~python
from dataclasses import asdict, replace

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
from decision_lab.replay_cohort import RoutingIntent
from decision_lab.research_budget import ResearchBudgetConfig, ResearchTier
from decision_lab.research_execution import (
    ResearchAuthorization,
    ResearchMode,
    ResearchRequirementScope,
    ResearchWorkOrderPolicy,
    build_research_work_order,
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


def _package(
    theme,
    *,
    adapter="industrials_infrastructure",
    effective_from="2026-01-01",
    version="p1",
    universe_version="u1",
):
    universe = ThemeUniverse(
        theme=theme,
        version=universe_version,
        generated_at="2026-09-19T00:00:00Z",
    )
    universe.add_layer(ThemeLayer("primary"))
    for ticker in ("AAA", "BBB"):
        universe.add_candidate(
            Candidate(
                ticker=ticker,
                theme=theme,
                layer="primary",
                effective_from=effective_from,
                provenance=(f"fixture:{ticker}",),
            )
        )
    return ThemePackage(
        definition=ThemeDefinition(
            theme_id=theme,
            display_name=theme,
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            effective_from=effective_from,
            version="1",
        ),
        universe=universe,
        theme_key_policy=ThemeKeyPolicy(),
        evidence_adapter=adapter,
        version=version,
        source_path="fixture",
    )


def _strong_observation(
    theme,
    *,
    direction=SupportDirection.SUPPORTING,
    independent=True,
):
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
        is_independent=independent,
        observed_or_inferred="observed",
    )


def _registered_archive(
    *,
    theme="WorkTheme",
    adapter="industrials_infrastructure",
    direction=SupportDirection.SUPPORTING,
    budget_config=None,
):
    package = _package(theme, adapter=adapter)
    bars = (
        MarketBar(
            symbol="SPY",
            session_date="2026-09-19",
            available_at="2026-09-19T21:00:00+00:00",
            close=100.0,
        ),
    )
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
                        version="test",
                    ),
                    market_config=MarketObservationConfig(),
                    bars=bars,
                    market_source_ref=f"fixture:{theme}:market",
                ),
            ),
            external_observations=(
                _strong_observation(theme, direction=direction),
            ),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=(
                ResearchBudgetConfig()
                if budget_config is None
                else budget_config
            ),
        )
    )
    return build_replay_archive_record(result), package


def _unregistered_forced_archive():
    theme = "UnknownRisk"
    result = run_replay_cycle(
        ReplayCycleInput(
            cycle_as_of="2026-09-19",
            themes=(),
            external_observations=(
                _strong_observation(
                    theme,
                    direction=SupportDirection.CONTRADICTING,
                ),
            ),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
    return build_replay_archive_record(result)
~~~

Add:

~~~python
def test_ordinary_full_company_work_order_is_deterministic():
    record, package = _registered_archive()

    first = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("BBB", "AAA"),
    )
    second = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA", "BBB"),
    )

    assert first == second
    assert first.authorization is ResearchAuthorization.ALLOCATED_FULL
    assert first.source_routing_intent is RoutingIntent.ORDINARY_FULL_RESEARCH
    assert first.source_allocated_tier is ResearchTier.FULL_DECISION_RESEARCH
    assert [target.ticker for target in first.targets] == ["AAA", "BBB"]
    assert first.evidence_adapter == "industrials_infrastructure"
    assert first.package_version == package.version
    assert first.universe_version == package.universe.version
    assert not first.package_lineage_exactly_recoverable
    assert first.contradiction_questions == ()
    assert len(first.policy_hash) == 64
    assert len(first.work_order_hash) == 64

    company_requirements = [
        item
        for item in first.requirements
        if item.scope is ResearchRequirementScope.COMPANY_EVIDENCE
    ]
    linkage_requirements = [
        item
        for item in first.requirements
        if item.scope is ResearchRequirementScope.COMPANY_LINKAGE
    ]
    assert company_requirements
    assert {item.target_ticker for item in company_requirements} == {"AAA", "BBB"}
    assert {item.target_ticker for item in linkage_requirements} == {"AAA", "BBB"}


def test_forced_full_theme_reassessment_has_contradiction_questions():
    record, package = _registered_archive(
        direction=SupportDirection.CONTRADICTING,
    )

    order = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.THEME_REASSESSMENT,
        theme_package=package,
    )

    assert order.source_routing_intent is RoutingIntent.FORCED_FULL_REVIEW
    assert order.authorization is ResearchAuthorization.ALLOCATED_FULL
    assert order.targets == ()
    assert order.contradiction_questions
    assert {
        item.scope for item in order.requirements
    } == {ResearchRequirementScope.THEME_EVIDENCE}


def test_unregistered_forced_review_preserves_scan_only_tier():
    record = _unregistered_forced_archive()

    order = build_research_work_order(
        record,
        "UnknownRisk",
        ResearchMode.THEME_REASSESSMENT,
    )

    assert order.source_routing_intent is RoutingIntent.FORCED_REVIEW_UNREGISTERED
    assert order.authorization is ResearchAuthorization.UNREGISTERED_FORCED_REVIEW
    assert order.source_allocated_tier is ResearchTier.SCAN_ONLY
    assert not order.source_registered
    assert order.evidence_adapter is None
    assert order.package_version is None
    assert order.universe_version is None
    assert order.targets == ()
~~~

- [ ] **Step 2: Add RED rejection/canonicalization tests**

~~~python
def test_unregistered_forced_review_cannot_be_company_deep_dive():
    record = _unregistered_forced_archive()

    with pytest.raises(
        ValueError,
        match="routing state is not executable in research v0.1|company deep dive",
    ):
        build_research_work_order(
            record,
            "UnknownRisk",
            ResearchMode.COMPANY_DEEP_DIVE,
            target_tickers=("AAA",),
        )


def test_capacity_missed_review_cannot_bypass_allocator():
    record, package = _registered_archive(
        direction=SupportDirection.CONTRADICTING,
        budget_config=replace(
            ResearchBudgetConfig(),
            full_decision_slots=0,
        ),
    )

    with pytest.raises(
        ValueError,
        match="routing state is not executable in research v0.1",
    ):
        build_research_work_order(
            record,
            "WorkTheme",
            ResearchMode.THEME_REASSESSMENT,
            theme_package=package,
        )


def test_company_deep_dive_rejects_generic_adapter():
    record, package = _registered_archive(adapter="generic")

    with pytest.raises(
        ValueError,
        match="generic adapter is not eligible for company deep dive",
    ):
        build_research_work_order(
            record,
            "WorkTheme",
            ResearchMode.COMPANY_DEEP_DIVE,
            theme_package=package,
            target_tickers=("AAA",),
        )


@pytest.mark.parametrize(
    "targets",
    [
        (),
        ("ZZZ",),
        ("AAA", "aaa"),
    ],
)
def test_company_targets_must_be_nonempty_unique_effective_members(targets):
    record, package = _registered_archive()

    with pytest.raises(ValueError):
        build_research_work_order(
            record,
            "WorkTheme",
            ResearchMode.COMPANY_DEEP_DIVE,
            theme_package=package,
            target_tickers=targets,
        )


def test_policy_dimension_order_is_semantic_set_order():
    record, package = _registered_archive()
    default = ResearchWorkOrderPolicy()
    reversed_policy = replace(
        default,
        industrials_company_dimensions=tuple(
            reversed(default.industrials_company_dimensions)
        ),
    )

    first = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
        policy=default,
    )
    second = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
        policy=reversed_policy,
    )

    assert first == second
~~~

- [ ] **Step 3: Run Task-1 tests and verify RED**

Run:

~~~bash
pytest -q tests/test_research_execution.py
~~~

Expected: collection failure because decision_lab.research_execution does not exist.

- [ ] **Step 4: Implement public WorkOrder enums/dataclasses/default policy**

Create src/decision_lab/research_execution.py with:

~~~python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from enum import Enum
from math import isfinite

from .adapters import (
    BiotechClinicalAdapter,
    CompanyEvidenceInput,
    IndustrialsInfrastructureAdapter,
    RawFactValue,
)
from .evidence import EvidenceRecord
from .hierarchical import HierarchicalLinkageResult
from .ledger import canonical_hash
from .linkage import LinkageResult
from .replay_archive import ReplayArchiveRecord
from .replay_cohort import RoutingIntent, evaluate_replay_cohort
from .research_budget import ResearchTier
from .themes import ThemePackage

SCHEMA_VERSION = "0.1"


class ResearchMode(str, Enum):
    THEME_REASSESSMENT = "THEME_REASSESSMENT"
    COMPANY_DEEP_DIVE = "COMPANY_DEEP_DIVE"


class ResearchAuthorization(str, Enum):
    ALLOCATED_FULL = "ALLOCATED_FULL"
    UNREGISTERED_FORCED_REVIEW = "UNREGISTERED_FORCED_REVIEW"


class ResearchRequirementScope(str, Enum):
    THEME_EVIDENCE = "THEME_EVIDENCE"
    COMPANY_EVIDENCE = "COMPANY_EVIDENCE"
    COMPANY_LINKAGE = "COMPANY_LINKAGE"


@dataclass(frozen=True)
class ResearchRequirement:
    scope: ResearchRequirementScope
    dimension: str
    target_ticker: str | None


@dataclass(frozen=True)
class ResearchTarget:
    ticker: str
    layer: str
    membership_state: str
    expression_role: str
    effective_from: str | None
    effective_to: str | None
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class ResearchWorkOrderPolicy:
    version: str = "0.1"
    theme_reassessment_dimensions: tuple[str, ...] = (
        "theme_structure",
        "independent_support",
        "independent_contradiction",
        "universe_integrity",
    )
    industrials_company_dimensions: tuple[str, ...] = (
        "growth",
        "margin_quality",
        "demand_visibility",
        "order_or_contract_visibility",
        "capital_intensity",
        "cash_generation",
        "balance_sheet_strength",
        "customer_concentration",
        "guidance_revision",
        "thesis_risk",
    )
    biotech_company_dimensions: tuple[str, ...] = (
        "clinical_phase",
        "endpoint_status",
        "regulatory_state",
        "cash_runway_months",
        "days_to_material_catalyst",
        "financing_risk",
        "platform_validation",
        "partnered_economics",
    )
    minimum_independent_sources: int = 2
    minimum_independent_sources_per_company: int = 1
    require_usable_linkage_for_company: bool = True


@dataclass(frozen=True)
class ResearchWorkOrder:
    schema_version: str
    source_archive_record_hash: str
    source_replay_result_hash: str
    source_cycle_as_of: str
    theme_id: str
    source_routing_intent: RoutingIntent
    source_registered: bool
    source_allocated_tier: ResearchTier
    source_forced_review: bool
    authorization: ResearchAuthorization
    research_mode: ResearchMode
    evidence_adapter: str | None
    package_version: str | None
    universe_version: str | None
    package_lineage_exactly_recoverable: bool
    targets: tuple[ResearchTarget, ...]
    requirements: tuple[ResearchRequirement, ...]
    minimum_independent_sources: int
    minimum_independent_sources_per_company: int
    contradiction_questions: tuple[str, ...]
    policy_hash: str
    work_order_hash: str
~~~

- [ ] **Step 5: Implement UTC/date and policy normalization**

~~~python
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


def _normalize_dimensions(
    values: Sequence[str],
    *,
    field_name: str,
) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError(f"{field_name} contains blank dimension")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} contains duplicate dimension")
    return tuple(sorted(normalized))


def _normalize_policy(
    policy: ResearchWorkOrderPolicy,
) -> ResearchWorkOrderPolicy:
    for name in (
        "minimum_independent_sources",
        "minimum_independent_sources_per_company",
    ):
        value = getattr(policy, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if not isinstance(policy.require_usable_linkage_for_company, bool):
        raise TypeError("require_usable_linkage_for_company must be bool")
    if not policy.version.strip():
        raise ValueError("research policy version must be non-empty")
    return replace(
        policy,
        version=policy.version.strip(),
        theme_reassessment_dimensions=_normalize_dimensions(
            policy.theme_reassessment_dimensions,
            field_name="theme_reassessment_dimensions",
        ),
        industrials_company_dimensions=_normalize_dimensions(
            policy.industrials_company_dimensions,
            field_name="industrials_company_dimensions",
        ),
        biotech_company_dimensions=_normalize_dimensions(
            policy.biotech_company_dimensions,
            field_name="biotech_company_dimensions",
        ),
    )
~~~

- [ ] **Step 6: Implement source transition extraction, package lineage, target and requirement builders**

~~~python
_CONTRADICTION_QUESTIONS = (
    "What independent evidence contradicts the current theme thesis?",
    "Is the contradiction persistent, structural, or coverage-related?",
    "What evidence would resolve rather than merely remove the contradiction?",
)


def _source_transition(
    record: ReplayArchiveRecord,
    theme_id: str,
):
    cohort = evaluate_replay_cohort((record,), horizons=(1,))
    matches = [
        item
        for item in cohort.transitions
        if item.theme_id == theme_id
    ]
    if len(matches) != 1:
        raise ValueError("theme missing from source replay")
    return matches[0]


def _effective_cycle_date(value: str) -> str:
    return _parse_utc(value).date().isoformat()


def _validate_package_lineage(
    record: ReplayArchiveRecord,
    theme_id: str,
    package: ThemePackage,
) -> tuple[str, str]:
    if (
        package.definition.theme_id != theme_id
        or package.universe.theme != theme_id
    ):
        raise ValueError("research package theme mismatch")

    cycle_date = _effective_cycle_date(record.cycle_as_of)
    definition = package.definition
    if (
        definition.effective_from is not None
        and cycle_date < definition.effective_from
    ) or (
        definition.effective_to is not None
        and cycle_date >= definition.effective_to
    ):
        raise ValueError("research package is not effective at source cycle")

    source_theme = next(
        (
            item
            for item in record.replay_result.theme_records
            if item.theme_id == theme_id
        ),
        None,
    )
    if source_theme is None or source_theme.market_batch is None:
        raise ValueError("source replay package lineage is inconsistent")

    package_versions = {
        item.package_version
        for item in source_theme.market_batch.diagnostics
    }
    universe_versions = {
        item.universe_version
        for item in source_theme.market_batch.diagnostics
    }
    if (
        len(package_versions) != 1
        or len(universe_versions) != 1
        or "" in package_versions
        or "" in universe_versions
    ):
        raise ValueError("source replay package lineage is inconsistent")

    replay_package_version = next(iter(package_versions))
    replay_universe_version = next(iter(universe_versions))
    if (
        replay_package_version != package.version
        or replay_universe_version != package.universe.version
    ):
        raise ValueError("source replay package lineage is inconsistent")
    return replay_package_version, replay_universe_version


def _company_dimensions(
    adapter_name: str,
    policy: ResearchWorkOrderPolicy,
) -> tuple[str, ...]:
    if adapter_name == "generic":
        raise ValueError(
            "generic adapter is not eligible for company deep dive"
        )
    if adapter_name == "industrials_infrastructure":
        return policy.industrials_company_dimensions
    if adapter_name == "biotech_clinical":
        return policy.biotech_company_dimensions
    raise ValueError("unsupported company evidence adapter")


def _build_targets(
    package: ThemePackage,
    cycle_date: str,
    target_tickers: Sequence[str],
) -> tuple[ResearchTarget, ...]:
    normalized = tuple(ticker.strip().upper() for ticker in target_tickers)
    if not normalized:
        raise ValueError("company deep dive requires target tickers")
    if any(not ticker for ticker in normalized):
        raise ValueError("company target ticker must be non-empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate company target ticker")

    active = {
        item.ticker.upper(): item
        for item in package.universe.active_candidates(as_of=cycle_date)
    }
    missing = [ticker for ticker in normalized if ticker not in active]
    if missing:
        raise ValueError("company target is not effective in source universe")

    return tuple(
        ResearchTarget(
            ticker=ticker,
            layer=active[ticker].layer,
            membership_state=active[ticker].membership_state,
            expression_role=active[ticker].expression_role,
            effective_from=active[ticker].effective_from,
            effective_to=active[ticker].effective_to,
            provenance=tuple(active[ticker].provenance),
        )
        for ticker in sorted(normalized)
    )


def _build_requirements(
    *,
    mode: ResearchMode,
    targets: tuple[ResearchTarget, ...],
    adapter_name: str | None,
    policy: ResearchWorkOrderPolicy,
) -> tuple[ResearchRequirement, ...]:
    rows: list[ResearchRequirement] = []
    if mode is ResearchMode.THEME_REASSESSMENT:
        rows.extend(
            ResearchRequirement(
                scope=ResearchRequirementScope.THEME_EVIDENCE,
                dimension=dimension,
                target_ticker=None,
            )
            for dimension in policy.theme_reassessment_dimensions
        )
    else:
        assert adapter_name is not None
        dimensions = _company_dimensions(adapter_name, policy)
        for target in targets:
            rows.extend(
                ResearchRequirement(
                    scope=ResearchRequirementScope.COMPANY_EVIDENCE,
                    dimension=dimension,
                    target_ticker=target.ticker,
                )
                for dimension in dimensions
            )
            if policy.require_usable_linkage_for_company:
                rows.append(
                    ResearchRequirement(
                        scope=ResearchRequirementScope.COMPANY_LINKAGE,
                        dimension="theme_linkage",
                        target_ticker=target.ticker,
                    )
                )
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                item.scope.value,
                item.target_ticker or "",
                item.dimension,
            ),
        )
    )
~~~

- [ ] **Step 7: Implement build_research_work_order and work-order hash**

~~~python
def _work_order_payload_without_hash(
    order: ResearchWorkOrder,
) -> dict[str, object]:
    payload = asdict(order)
    payload.pop("work_order_hash")
    return payload


def _validate_work_order_hash(order: ResearchWorkOrder) -> None:
    if canonical_hash(_work_order_payload_without_hash(order)) != order.work_order_hash:
        raise ValueError("invalid research work order")


def build_research_work_order(
    source_record: ReplayArchiveRecord,
    theme_id: str,
    research_mode: ResearchMode,
    *,
    theme_package: ThemePackage | None = None,
    target_tickers: Sequence[str] = (),
    policy: ResearchWorkOrderPolicy = ResearchWorkOrderPolicy(),
) -> ResearchWorkOrder:
    if not isinstance(research_mode, ResearchMode):
        raise TypeError("unsupported research mode")
    theme_id = theme_id.strip()
    if not theme_id:
        raise ValueError("theme_id must be non-empty")

    normalized_policy = _normalize_policy(policy)
    transition = _source_transition(source_record, theme_id)

    eligible_full = {
        RoutingIntent.ORDINARY_FULL_RESEARCH,
        RoutingIntent.FORCED_FULL_REVIEW,
    }
    if transition.routing_intent is RoutingIntent.FORCED_REVIEW_UNREGISTERED:
        if research_mode is not ResearchMode.THEME_REASSESSMENT:
            raise ValueError(
                "unregistered forced review cannot create company deep dive"
            )
        if theme_package is not None or tuple(target_tickers):
            raise ValueError(
                "unregistered forced review cannot create company deep dive"
            )
        authorization = ResearchAuthorization.UNREGISTERED_FORCED_REVIEW
        adapter_name = None
        package_version = None
        universe_version = None
        targets = ()
    elif transition.routing_intent in eligible_full:
        if theme_package is None:
            raise ValueError("registered research requires ThemePackage")
        package_version, universe_version = _validate_package_lineage(
            source_record,
            theme_id,
            theme_package,
        )
        authorization = ResearchAuthorization.ALLOCATED_FULL
        adapter_name = theme_package.evidence_adapter
        if research_mode is ResearchMode.COMPANY_DEEP_DIVE:
            targets = _build_targets(
                theme_package,
                _effective_cycle_date(source_record.cycle_as_of),
                target_tickers,
            )
            _company_dimensions(adapter_name, normalized_policy)
        else:
            if tuple(target_tickers):
                raise ValueError(
                    "theme reassessment does not accept company targets"
                )
            targets = ()
    else:
        raise ValueError(
            "routing state is not executable in research v0.1"
        )

    if transition.source_tier is None or transition.source_forced_review is None:
        raise ValueError("routing state is not executable in research v0.1")

    requirements = _build_requirements(
        mode=research_mode,
        targets=targets,
        adapter_name=adapter_name,
        policy=normalized_policy,
    )
    policy_hash = canonical_hash(asdict(normalized_policy))
    contradiction_questions = (
        _CONTRADICTION_QUESTIONS
        if transition.source_forced_review
        else ()
    )

    seed = ResearchWorkOrder(
        schema_version=SCHEMA_VERSION,
        source_archive_record_hash=source_record.archive_record_hash,
        source_replay_result_hash=source_record.replay_result_hash,
        source_cycle_as_of=source_record.cycle_as_of,
        theme_id=theme_id,
        source_routing_intent=transition.routing_intent,
        source_registered=transition.source_registered,
        source_allocated_tier=transition.source_tier,
        source_forced_review=transition.source_forced_review,
        authorization=authorization,
        research_mode=research_mode,
        evidence_adapter=adapter_name,
        package_version=package_version,
        universe_version=universe_version,
        package_lineage_exactly_recoverable=False,
        targets=targets,
        requirements=requirements,
        minimum_independent_sources=(
            normalized_policy.minimum_independent_sources
        ),
        minimum_independent_sources_per_company=(
            normalized_policy.minimum_independent_sources_per_company
        ),
        contradiction_questions=contradiction_questions,
        policy_hash=policy_hash,
        work_order_hash="0" * 64,
    )
    order = replace(
        seed,
        work_order_hash=canonical_hash(
            _work_order_payload_without_hash(seed)
        ),
    )
    _validate_work_order_hash(order)
    return order
~~~

- [ ] **Step 8: Run Task-1 tests and full regression**

Run:

~~~bash
pytest -q tests/test_research_execution.py
pytest -q
~~~

Expected: PASS.

- [ ] **Step 9: Commit**

~~~bash
git add src/decision_lab/research_execution.py tests/test_research_execution.py
git commit -m "feat: add deterministic research work orders"
~~~

---

### Task 2: Evidence validation, immutable evidence snapshots, findings, time/scope rules

**Files:**
- Modify: src/decision_lab/research_execution.py
- Modify: tests/test_research_execution.py

**Interfaces:**
- Produces:
  - ResearchEvidenceDirection
  - ResearchEvidenceInput
  - FrozenResearchEvidence
  - ResearchEvidenceBinding
  - ResearchFindingKind
  - ResearchFinding
- Private:
  - _validate_evidence_record
  - _freeze_evidence_inputs
  - _normalize_findings
  - _validate_finding_scope

- [ ] **Step 1: Add RED evidence helpers and hash/time/scope tests**

Append imports:

~~~python
from decision_lab.evidence import EvidenceRecord
from decision_lab.research_execution import (
    ResearchEvidenceDirection,
    ResearchEvidenceInput,
    ResearchFinding,
    ResearchFindingKind,
    _freeze_evidence_inputs,
    _normalize_findings,
    _parse_utc,
)
~~~

Add explicit deterministic evidence helper:

~~~python
def _evidence(
    *,
    evidence_id,
    source_ref,
    payload,
    theme="WorkTheme",
    ticker=None,
    source_type="sec_filing",
    observed_at="2026-09-20T12:00:00+00:00",
    retrieved_at="2026-09-20T13:00:00+00:00",
    market_asof=None,
    is_observed_fact=True,
):
    raw = EvidenceRecord(
        evidence_id=evidence_id,
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        market_asof=market_asof,
        ticker=ticker,
        theme=theme,
        source_type=source_type,
        source_ref=source_ref,
        fact_type="research_fact",
        payload=dict(payload),
        is_observed_fact=is_observed_fact,
    )
    return raw.with_hash()
~~~

Add:

~~~python
def test_stale_evidence_hash_is_rejected():
    record, package = _registered_archive()
    order = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
    )
    evidence = _evidence(
        evidence_id="ev1",
        source_ref="sec:aaa",
        ticker="AAA",
        payload={"growth": 0.2},
    )
    evidence.payload["growth"] = 0.3

    with pytest.raises(
        ValueError,
        match="invalid research evidence hash",
    ):
        _freeze_evidence_inputs(
            (
                ResearchEvidenceInput(
                    evidence=evidence,
                    independent=True,
                    direction=ResearchEvidenceDirection.SUPPORTING,
                    dimensions=("growth",),
                    target_ticker="AAA",
                ),
            ),
            order=order,
            evidence_as_of=_parse_utc(
                "2026-09-20T23:00:00+00:00"
            ),
        )


@pytest.mark.parametrize(
    ("source_type", "observed"),
    [
        ("radar_model_output", True),
        ("derived_feature", False),
    ],
)
def test_model_or_inferred_evidence_cannot_be_marked_independent(
    source_type,
    observed,
):
    record, package = _registered_archive()
    order = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
    )
    evidence = _evidence(
        evidence_id="ev1",
        source_ref="model:aaa",
        ticker="AAA",
        payload={"growth": 0.2},
        source_type=source_type,
        is_observed_fact=observed,
    )

    with pytest.raises(
        ValueError,
        match="model or inferred evidence cannot be marked independent",
    ):
        _freeze_evidence_inputs(
            (
                ResearchEvidenceInput(
                    evidence=evidence,
                    independent=True,
                    direction=ResearchEvidenceDirection.SUPPORTING,
                    dimensions=("growth",),
                    target_ticker="AAA",
                ),
            ),
            order=order,
            evidence_as_of=_parse_utc(
                "2026-09-20T23:00:00+00:00"
            ),
        )


def test_future_evidence_is_rejected():
    record, package = _registered_archive()
    order = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
    )
    evidence = _evidence(
        evidence_id="ev1",
        source_ref="sec:aaa",
        ticker="AAA",
        payload={"growth": 0.2},
        observed_at="2026-09-21T00:00:00+00:00",
        retrieved_at="2026-09-21T00:05:00+00:00",
    )

    with pytest.raises(
        ValueError,
        match="research evidence exceeds evidence_as_of",
    ):
        _freeze_evidence_inputs(
            (
                ResearchEvidenceInput(
                    evidence=evidence,
                    independent=True,
                    direction=ResearchEvidenceDirection.SUPPORTING,
                    dimensions=("growth",),
                    target_ticker="AAA",
                ),
            ),
            order=order,
            evidence_as_of=_parse_utc(
                "2026-09-20T23:00:00+00:00"
            ),
        )


def test_cross_company_evidence_is_rejected():
    record, package = _registered_archive()
    order = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
    )
    evidence = _evidence(
        evidence_id="ev1",
        source_ref="sec:bbb",
        ticker="BBB",
        payload={"growth": 0.2},
    )

    with pytest.raises(ValueError):
        _freeze_evidence_inputs(
            (
                ResearchEvidenceInput(
                    evidence=evidence,
                    independent=True,
                    direction=ResearchEvidenceDirection.SUPPORTING,
                    dimensions=("growth",),
                    target_ticker="AAA",
                ),
            ),
            order=order,
            evidence_as_of=_parse_utc("2026-09-20"),
        )


def test_evidence_payload_is_frozen_by_snapshot():
    record, package = _registered_archive()
    order = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
    )
    evidence = _evidence(
        evidence_id="ev1",
        source_ref="sec:aaa",
        ticker="AAA",
        payload={"growth": 0.2},
    )
    bindings, _ = _freeze_evidence_inputs(
        (
            ResearchEvidenceInput(
                evidence=evidence,
                independent=True,
                direction=ResearchEvidenceDirection.SUPPORTING,
                dimensions=("growth",),
                target_ticker="AAA",
            ),
        ),
        order=order,
        evidence_as_of=_parse_utc("2026-09-20"),
    )
    before = bindings
    evidence.payload["growth"] = 99.0

    assert bindings == before
    assert bindings[0].evidence.payload_hash == canonical_hash(
        {"growth": 0.2}
    )


def test_observed_synthesis_cannot_cite_non_observed_evidence():
    record = _unregistered_forced_archive()
    order = build_research_work_order(
        record,
        "UnknownRisk",
        ResearchMode.THEME_REASSESSMENT,
    )
    model = _evidence(
        evidence_id="ev1",
        source_ref="model:risk",
        theme="UnknownRisk",
        payload={"theme_structure": "weak"},
        source_type="radar_model_output",
        is_observed_fact=False,
    )
    bindings, originals = _freeze_evidence_inputs(
        (
            ResearchEvidenceInput(
                evidence=model,
                independent=False,
                direction=ResearchEvidenceDirection.CONTRADICTING,
                dimensions=("theme_structure",),
                target_ticker=None,
            ),
        ),
        order=order,
        evidence_as_of=_parse_utc("2026-09-20"),
    )
    assert bindings

    with pytest.raises(ValueError):
        _normalize_findings(
            (
                ResearchFinding(
                    finding_id="f1",
                    kind=ResearchFindingKind.OBSERVED_SYNTHESIS,
                    direction=ResearchEvidenceDirection.CONTRADICTING,
                    dimension="theme_structure",
                    target_ticker=None,
                    statement="Structure is weak.",
                    evidence_source_hashes=(model.source_hash,),
                ),
            ),
            order=order,
            evidence=originals,
        )


def test_unresolved_finding_can_be_evidence_free_but_has_no_direction():
    record = _unregistered_forced_archive()
    order = build_research_work_order(
        record,
        "UnknownRisk",
        ResearchMode.THEME_REASSESSMENT,
    )
    findings = _normalize_findings(
        (
            ResearchFinding(
                finding_id="open-question",
                kind=ResearchFindingKind.UNRESOLVED,
                direction=None,
                dimension="theme_structure",
                target_ticker=None,
                statement="Need stronger primary evidence.",
                evidence_source_hashes=(),
            ),
        ),
        order=order,
        evidence={},
    )

    assert findings[0].kind is ResearchFindingKind.UNRESOLVED
    assert findings[0].direction is None
~~~

- [ ] **Step 3: Run Task-2 tests and verify RED**

Run:

~~~bash
pytest -q tests/test_research_execution.py
~~~

Expected: failures because dossier/evidence types and builder do not exist.

- [ ] **Step 4: Implement evidence/finding public types and snapshot helpers**

Add:

~~~python
class ResearchEvidenceDirection(str, Enum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class ResearchEvidenceInput:
    evidence: EvidenceRecord
    independent: bool
    direction: ResearchEvidenceDirection
    dimensions: tuple[str, ...]
    target_ticker: str | None


@dataclass(frozen=True)
class FrozenResearchEvidence:
    evidence_id: str
    source_hash: str
    payload_hash: str
    observed_at: str
    retrieved_at: str | None
    market_asof: str | None
    ticker: str | None
    theme: str | None
    source_type: str
    source_ref: str
    fact_type: str
    is_observed_fact: bool
    model_version: str | None
    notes: str | None


@dataclass(frozen=True)
class ResearchEvidenceBinding:
    evidence: FrozenResearchEvidence
    independent: bool
    direction: ResearchEvidenceDirection
    dimensions: tuple[str, ...]
    target_ticker: str | None


class ResearchFindingKind(str, Enum):
    OBSERVED_SYNTHESIS = "OBSERVED_SYNTHESIS"
    INFERENCE = "INFERENCE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ResearchFinding:
    finding_id: str
    kind: ResearchFindingKind
    direction: ResearchEvidenceDirection | None
    dimension: str
    target_ticker: str | None
    statement: str
    evidence_source_hashes: tuple[str, ...]


class ResearchExecutionClosure(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
~~~

Add validation/freeze helpers:

~~~python
def _validate_evidence_record(record: EvidenceRecord) -> None:
    digest = record.source_hash
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
    ):
        raise ValueError("invalid research evidence hash")
    payload = asdict(record)
    payload["source_hash"] = None
    if canonical_hash(payload) != digest:
        raise ValueError("invalid research evidence hash")


def _freeze_evidence(
    item: ResearchEvidenceInput,
    *,
    order: ResearchWorkOrder,
    evidence_as_of: datetime,
) -> ResearchEvidenceBinding:
    evidence = item.evidence
    _validate_evidence_record(evidence)
    if not isinstance(item.independent, bool):
        raise TypeError("independent must be bool")
    if not isinstance(item.direction, ResearchEvidenceDirection):
        raise TypeError("unsupported research evidence direction")
    if (
        item.independent
        and (
            evidence.source_type == "radar_model_output"
            or not evidence.is_observed_fact
        )
    ):
        raise ValueError(
            "model or inferred evidence cannot be marked independent"
        )

    for value in (
        evidence.observed_at,
        evidence.market_asof,
        evidence.retrieved_at,
    ):
        if value is not None and _parse_utc(value) > evidence_as_of:
            raise ValueError("research evidence exceeds evidence_as_of")

    targets = {target.ticker for target in order.targets}
    ticker = None if evidence.ticker is None else evidence.ticker.upper()
    target_ticker = (
        None
        if item.target_ticker is None
        else item.target_ticker.strip().upper()
    )
    if evidence.theme is not None and evidence.theme != order.theme_id:
        raise ValueError("research evidence is outside work-order scope")
    if ticker is not None and ticker not in targets:
        raise ValueError("research evidence is outside work-order scope")
    if evidence.theme is None and ticker is None:
        raise ValueError("research evidence is outside work-order scope")
    if order.research_mode is ResearchMode.THEME_REASSESSMENT:
        if target_ticker is not None or ticker is not None:
            raise ValueError("theme reassessment requires theme-level evidence")
    elif target_ticker not in targets:
        raise ValueError("research evidence target is outside work-order scope")

    dimensions = _normalize_dimensions(
        item.dimensions,
        field_name="research evidence dimensions",
    )
    frozen = FrozenResearchEvidence(
        evidence_id=evidence.evidence_id,
        source_hash=evidence.source_hash,
        payload_hash=canonical_hash(evidence.payload),
        observed_at=evidence.observed_at,
        retrieved_at=evidence.retrieved_at,
        market_asof=evidence.market_asof,
        ticker=ticker,
        theme=evidence.theme,
        source_type=evidence.source_type,
        source_ref=evidence.source_ref,
        fact_type=evidence.fact_type,
        is_observed_fact=evidence.is_observed_fact,
        model_version=evidence.model_version,
        notes=evidence.notes,
    )
    return ResearchEvidenceBinding(
        evidence=frozen,
        independent=item.independent,
        direction=item.direction,
        dimensions=dimensions,
        target_ticker=target_ticker,
    )
~~~

- [ ] **Step 5: Implement canonical evidence collection and finding validation**

~~~python
def _freeze_evidence_inputs(
    inputs: Sequence[ResearchEvidenceInput],
    *,
    order: ResearchWorkOrder,
    evidence_as_of: datetime,
) -> tuple[
    tuple[ResearchEvidenceBinding, ...],
    dict[str, EvidenceRecord],
]:
    bindings: list[ResearchEvidenceBinding] = []
    originals: dict[str, EvidenceRecord] = {}
    source_metadata: dict[str, tuple[bool, str]] = {}
    for item in inputs:
        binding = _freeze_evidence(
            item,
            order=order,
            evidence_as_of=evidence_as_of,
        )
        digest = binding.evidence.source_hash
        if digest in originals:
            raise ValueError("duplicate research evidence hash")
        metadata = (
            binding.independent,
            binding.evidence.source_type,
        )
        previous = source_metadata.get(binding.evidence.source_ref)
        if previous is not None and previous != metadata:
            raise ValueError("conflicting research source metadata")
        source_metadata[binding.evidence.source_ref] = metadata
        originals[digest] = item.evidence
        bindings.append(binding)

    return (
        tuple(
            sorted(
                bindings,
                key=lambda item: (
                    item.evidence.source_hash,
                    item.target_ticker or "",
                    item.direction.value,
                    item.dimensions,
                ),
            )
        ),
        originals,
    )


def _normalize_findings(
    findings: Sequence[ResearchFinding],
    *,
    order: ResearchWorkOrder,
    evidence: Mapping[str, EvidenceRecord],
) -> tuple[ResearchFinding, ...]:
    targets = {target.ticker for target in order.targets}
    output: list[ResearchFinding] = []
    seen_ids: set[str] = set()
    for item in findings:
        finding_id = item.finding_id.strip()
        dimension = item.dimension.strip()
        statement = item.statement.strip()
        if not finding_id or not dimension or not statement:
            raise ValueError("research finding fields must be non-empty")
        if finding_id in seen_ids:
            raise ValueError("duplicate research finding_id")
        seen_ids.add(finding_id)

        target = (
            None
            if item.target_ticker is None
            else item.target_ticker.strip().upper()
        )
        if target is not None and target not in targets:
            raise ValueError("research finding target outside work order")

        hashes = tuple(sorted(item.evidence_source_hashes))
        if len(set(hashes)) != len(hashes):
            raise ValueError("duplicate research finding evidence hash")
        if any(digest not in evidence for digest in hashes):
            raise ValueError("research finding references unknown evidence")

        if item.kind is ResearchFindingKind.UNRESOLVED:
            if item.direction is not None:
                raise ValueError("unresolved finding cannot have direction")
        else:
            if item.direction is None or not hashes:
                raise ValueError("research finding requires evidence and direction")
            if (
                item.kind is ResearchFindingKind.OBSERVED_SYNTHESIS
                and any(not evidence[digest].is_observed_fact for digest in hashes)
            ):
                raise ValueError(
                    "observed synthesis requires observed evidence"
                )

        for digest in hashes:
            record = evidence[digest]
            record_ticker = (
                None if record.ticker is None else record.ticker.upper()
            )
            if target is not None and record_ticker not in (None, target):
                raise ValueError("research finding cites another target company")

        output.append(
            ResearchFinding(
                finding_id=finding_id,
                kind=item.kind,
                direction=item.direction,
                dimension=dimension,
                target_ticker=target,
                statement=statement,
                evidence_source_hashes=hashes,
            )
        )
    return tuple(sorted(output, key=lambda item: item.finding_id))
~~~

Task 4 will call these helpers from build_research_dossier.

- [ ] **Step 6: Run Task-2 tests and full regression**

Run:

~~~bash
pytest -q tests/test_research_execution.py
pytest -q
~~~

Expected: all evidence/finding helper tests pass without any ResearchDossier implementation.

- [ ] **Step 7: Commit**

~~~bash
git add src/decision_lab/research_execution.py tests/test_research_execution.py
git commit -m "feat: freeze research evidence and findings"
~~~

---

### Task 3: Company submissions, adapter snapshots, linkage snapshots, and requirement-level company coverage

**Files:**
- Modify: src/decision_lab/research_execution.py
- Modify: tests/test_research_execution.py

**Interfaces:**
- Produces:
  - CompanyResearchSubmission
  - NormalizedCompanyField
  - NormalizedCompanySnapshot
  - CompanyLinkageSubmission
  - HierarchicalLinkageSnapshot
  - CompanyLinkageStatus
  - CompanyResearchAssessment
- Private:
  - _build_company_assessments
  - _snapshot_hierarchical_linkage
  - _linkage_status

- [ ] **Step 1: Add RED company raw-fact, adapter, and completion-field tests**

Append imports:

~~~python
from decision_lab.hierarchical import HierarchicalLinkageResult
from decision_lab.linkage import LinkageResult
from decision_lab.research_execution import (
    CompanyLinkageSubmission,
    CompanyLinkageStatus,
    CompanyResearchSubmission,
    _build_company_assessments,
    _linkage_status,
    _normalize_company_submissions,
    _normalize_linkage_submissions,
)
~~~

Add:

~~~python
def _company_order(adapter="industrials_infrastructure"):
    record, package = _registered_archive(adapter=adapter)
    return build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
    )


def _one_company_binding(order, evidence, dimensions):
    return _freeze_evidence_inputs(
        (
            ResearchEvidenceInput(
                evidence=evidence,
                independent=True,
                direction=ResearchEvidenceDirection.SUPPORTING,
                dimensions=dimensions,
                target_ticker="AAA",
            ),
        ),
        order=order,
        evidence_as_of=_parse_utc("2026-09-20"),
    )


def test_company_raw_fact_requires_same_ticker_evidence():
    order = _company_order()
    theme_evidence = _evidence(
        evidence_id="theme",
        source_ref="industry:theme",
        ticker=None,
        payload={"revenue_growth": 0.2},
    )
    _, originals = _one_company_binding(
        order,
        theme_evidence,
        ("growth",),
    )

    with pytest.raises(
        ValueError,
        match="company raw fact is unsupported by cited evidence",
    ):
        _normalize_company_submissions(
            (
                CompanyResearchSubmission(
                    ticker="AAA",
                    as_of="2026-09-20",
                    adapter_name="industrials_infrastructure",
                    raw_facts={"revenue_growth": 0.2},
                    evidence_source_hashes=(theme_evidence.source_hash,),
                ),
            ),
            order=order,
            evidence=originals,
            evidence_as_of=_parse_utc("2026-09-20"),
        )


def test_type_sensitive_raw_fact_support_rejects_bool_for_one():
    order = _company_order()
    evidence = _evidence(
        evidence_id="aaa",
        source_ref="sec:aaa",
        ticker="AAA",
        payload={"revenue_growth": True},
    )
    _, originals = _one_company_binding(order, evidence, ("growth",))

    with pytest.raises(
        ValueError,
        match="company raw fact is unsupported by cited evidence",
    ):
        _normalize_company_submissions(
            (
                CompanyResearchSubmission(
                    ticker="AAA",
                    as_of="2026-09-20",
                    adapter_name="industrials_infrastructure",
                    raw_facts={"revenue_growth": 1},
                    evidence_source_hashes=(evidence.source_hash,),
                ),
            ),
            order=order,
            evidence=originals,
            evidence_as_of=_parse_utc("2026-09-20"),
        )


def test_declared_company_dimension_does_not_create_missing_normalized_field():
    order = _company_order()
    evidence = _evidence(
        evidence_id="aaa",
        source_ref="sec:aaa",
        ticker="AAA",
        payload={"unrelated": 1},
    )
    _, originals = _one_company_binding(order, evidence, ("growth",))
    snapshots = _normalize_company_submissions(
        (
            CompanyResearchSubmission(
                ticker="AAA",
                as_of="2026-09-20",
                adapter_name="industrials_infrastructure",
                raw_facts={"unrelated": 1},
                evidence_source_hashes=(evidence.source_hash,),
            ),
        ),
        order=order,
        evidence=originals,
        evidence_as_of=_parse_utc("2026-09-20"),
    )

    assert "growth" not in {
        item.name for item in snapshots["AAA"].fields
    }


def test_industrials_adapter_snapshot_preserves_domain_fields():
    order = _company_order("industrials_infrastructure")
    evidence = _evidence(
        evidence_id="aaa",
        source_ref="sec:aaa",
        ticker="AAA",
        payload={
            "revenue_growth": 0.2,
            "gross_margin": 0.3,
            "backlog_growth": 0.4,
        },
    )
    _, originals = _one_company_binding(
        order,
        evidence,
        ("growth", "margin_quality", "demand_visibility"),
    )
    snapshots = _normalize_company_submissions(
        (
            CompanyResearchSubmission(
                ticker="AAA",
                as_of="2026-09-20",
                adapter_name="industrials_infrastructure",
                raw_facts=dict(evidence.payload),
                evidence_source_hashes=(evidence.source_hash,),
            ),
        ),
        order=order,
        evidence=originals,
        evidence_as_of=_parse_utc("2026-09-20"),
    )
    fields_by_name = {
        item.name: item.value for item in snapshots["AAA"].fields
    }
    assert fields_by_name["growth"] is not None
    assert fields_by_name["margin_quality"] is not None
    assert fields_by_name["demand_visibility"] is not None


def test_biotech_adapter_snapshot_preserves_clinical_fields():
    order = _company_order("biotech_clinical")
    evidence = _evidence(
        evidence_id="aaa",
        source_ref="ir:aaa",
        ticker="AAA",
        payload={
            "clinical_phase": "Phase 2",
            "endpoint_status": "met",
            "regulatory_state": "active",
            "cash_runway_months": 24,
            "days_to_material_catalyst": 45,
            "platform_validation": 0.8,
            "partnered_economics": 0.7,
        },
    )
    _, originals = _one_company_binding(
        order,
        evidence,
        (
            "clinical_phase",
            "endpoint_status",
            "regulatory_state",
            "cash_runway_months",
            "days_to_material_catalyst",
            "platform_validation",
            "partnered_economics",
        ),
    )
    snapshots = _normalize_company_submissions(
        (
            CompanyResearchSubmission(
                ticker="AAA",
                as_of="2026-09-20",
                adapter_name="biotech_clinical",
                raw_facts=dict(evidence.payload),
                evidence_source_hashes=(evidence.source_hash,),
            ),
        ),
        order=order,
        evidence=originals,
        evidence_as_of=_parse_utc("2026-09-20"),
    )
    fields_by_name = {
        item.name: item.value for item in snapshots["AAA"].fields
    }
    assert fields_by_name["clinical_phase"] == "Phase 2"
    assert fields_by_name["cash_runway_months"] == 24


def _usable_linkage():
    return LinkageResult(
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


def test_circular_linkage_status_is_not_usable():
    order = _company_order()
    linkage = replace(_usable_linkage(), circularity_warning=True)
    linkage_map = _normalize_linkage_submissions(
        (
            CompanyLinkageSubmission(
                ticker="AAA",
                linkage=linkage,
            ),
        ),
        order=order,
    )
    simple, hierarchical = linkage_map["AAA"]

    assert (
        _linkage_status(simple, hierarchical)
        is CompanyLinkageStatus.CIRCULARITY_WARNING
    )


def test_hierarchical_coefficients_are_frozen():
    order = _company_order()
    coefficients = {"SPY": 0.4, "WorkTheme": 0.6}
    hierarchical = HierarchicalLinkageResult(
        target="AAA",
        status="ok",
        window=63,
        observations=63,
        theme_correlation=0.6,
        theme_beta=0.6,
        r2=0.5,
        incremental_theme_r2=0.2,
        residual_mean=0.0,
        residual_vol=0.02,
        circularity_warning=False,
        missing_controls=(),
        coefficients=coefficients,
    )
    linkage_map = _normalize_linkage_submissions(
        (
            CompanyLinkageSubmission(
                ticker="AAA",
                hierarchical_linkage=hierarchical,
            ),
        ),
        order=order,
    )
    snapshot = linkage_map["AAA"][1]
    coefficients["SPY"] = 99.0

    assert snapshot.coefficients == (
        ("SPY", 0.4),
        ("WorkTheme", 0.6),
    )
~~~

- [ ] **Step 4: Run Task-3 tests and verify RED**

Run:

~~~bash
pytest -q tests/test_research_execution.py
~~~

Expected: failures for missing company/linkage output types and logic.

- [ ] **Step 5: Implement company/linkage public snapshot types**

Add:

~~~python
@dataclass(frozen=True)
class CompanyResearchSubmission:
    ticker: str
    as_of: str
    adapter_name: str
    raw_facts: Mapping[str, RawFactValue]
    evidence_source_hashes: tuple[str, ...]


@dataclass(frozen=True)
class NormalizedCompanyField:
    name: str
    value: float | int | str


@dataclass(frozen=True)
class NormalizedCompanySnapshot:
    ticker: str
    as_of: str
    adapter_name: str
    source_coverage: str
    provenance: tuple[str, ...]
    fields: tuple[NormalizedCompanyField, ...]
    normalized_payload_hash: str


@dataclass(frozen=True)
class CompanyLinkageSubmission:
    ticker: str
    linkage: LinkageResult | None = None
    hierarchical_linkage: HierarchicalLinkageResult | None = None


@dataclass(frozen=True)
class HierarchicalLinkageSnapshot:
    target: str
    status: str
    window: int
    observations: int
    theme_correlation: float | None
    theme_beta: float | None
    r2: float | None
    incremental_theme_r2: float | None
    residual_mean: float | None
    residual_vol: float | None
    circularity_warning: bool
    missing_controls: tuple[str, ...]
    coefficients: tuple[tuple[str, float], ...]
    source_payload_hash: str


class CompanyLinkageStatus(str, Enum):
    USABLE = "USABLE"
    COVERAGE_PENDING = "COVERAGE_PENDING"
    CIRCULARITY_WARNING = "CIRCULARITY_WARNING"
    NOT_PROVIDED = "NOT_PROVIDED"


@dataclass(frozen=True)
class CompanyResearchAssessment:
    ticker: str
    normalized_evidence: NormalizedCompanySnapshot | None
    evidence_source_hashes: tuple[str, ...]
    independent_source_count: int
    covered_dimensions: tuple[str, ...]
    linkage_status: CompanyLinkageStatus
    linkage: LinkageResult | None
    hierarchical_linkage: HierarchicalLinkageSnapshot | None
    cautions: tuple[str, ...]
~~~

The normalized_evidence field is optional so a PARTIAL dossier can represent linkage-only or evidence-only progress before a company submission exists.

- [ ] **Step 6: Implement company submission canonicalization, adapter dispatch, normalized snapshots**

~~~python
def _canonical_raw_facts(
    raw_facts: Mapping[str, RawFactValue],
) -> dict[str, RawFactValue]:
    output: dict[str, RawFactValue] = {}
    for key, value in raw_facts.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("company raw-fact key must be non-empty")
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float, str))
        ):
            raise TypeError("unsupported company raw-fact value")
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("company raw-fact value must be finite")
        output[key.strip()] = value
    return output


def _adapter_for(name: str):
    if name == "industrials_infrastructure":
        return IndustrialsInfrastructureAdapter()
    if name == "biotech_clinical":
        return BiotechClinicalAdapter()
    if name == "generic":
        raise ValueError(
            "generic adapter is not eligible for company deep dive"
        )
    raise ValueError("unsupported company evidence adapter")


def _snapshot_normalized(
    normalized,
    *,
    adapter_name: str,
) -> NormalizedCompanySnapshot:
    payload = asdict(normalized)
    digest = canonical_hash(payload)
    excluded = {
        "ticker",
        "as_of",
        "source_coverage",
        "provenance",
        "raw_facts",
    }
    output_fields: list[NormalizedCompanyField] = []
    for field in fields(normalized):
        if field.name in excluded:
            continue
        value = getattr(normalized, field.name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(
            value,
            (int, float, str),
        ):
            raise TypeError("unsupported normalized company field type")
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("normalized company field must be finite")
        output_fields.append(
            NormalizedCompanyField(field.name, value)
        )
    return NormalizedCompanySnapshot(
        ticker=normalized.ticker,
        as_of=normalized.as_of,
        adapter_name=adapter_name,
        source_coverage=normalized.source_coverage,
        provenance=tuple(normalized.provenance),
        fields=tuple(
            sorted(output_fields, key=lambda item: item.name)
        ),
        normalized_payload_hash=digest,
    )
~~~

- [ ] **Step 7: Implement raw-fact support and company assessments**

~~~python
def _canonical_value_equal(left, right) -> bool:
    return canonical_hash({"value": left}) == canonical_hash({"value": right})


def _normalize_company_submissions(
    submissions: Sequence[CompanyResearchSubmission],
    *,
    order: ResearchWorkOrder,
    evidence: Mapping[str, EvidenceRecord],
    evidence_as_of: datetime,
) -> dict[str, NormalizedCompanySnapshot]:
    targets = {target.ticker for target in order.targets}
    output: dict[str, NormalizedCompanySnapshot] = {}
    for submission in submissions:
        ticker = submission.ticker.strip().upper()
        if ticker not in targets:
            raise ValueError("company submission target outside work order")
        if ticker in output:
            raise ValueError("duplicate company research submission")
        if submission.adapter_name != order.evidence_adapter:
            raise ValueError("company adapter does not match work order")
        company_as_of = _parse_utc(submission.as_of)
        source_as_of = _parse_utc(order.source_cycle_as_of)
        if company_as_of < source_as_of or company_as_of > evidence_as_of:
            raise ValueError(
                "company research as_of is outside execution window"
            )

        hashes = tuple(sorted(submission.evidence_source_hashes))
        if len(set(hashes)) != len(hashes):
            raise ValueError("duplicate company evidence hash")
        if any(digest not in evidence for digest in hashes):
            raise ValueError("company submission references unknown evidence")

        raw_facts = _canonical_raw_facts(submission.raw_facts)
        for key, value in raw_facts.items():
            supported = any(
                record.ticker is not None
                and record.ticker.upper() == ticker
                and key in record.payload
                and _canonical_value_equal(record.payload[key], value)
                for digest, record in evidence.items()
                if digest in hashes
            )
            if not supported:
                raise ValueError(
                    "company raw fact is unsupported by cited evidence"
                )

        normalized = _adapter_for(
            submission.adapter_name
        ).normalize(
            CompanyEvidenceInput(
                ticker=ticker,
                as_of=submission.as_of,
                raw_facts=dict(raw_facts),
                provenance=hashes,
            )
        )
        output[ticker] = _snapshot_normalized(
            normalized,
            adapter_name=submission.adapter_name,
        )
    return output
~~~

- [ ] **Step 8: Implement linkage validation/snapshots/status**

~~~python
def _finite_optional(value, *, field_name: str) -> None:
    if value is not None and not isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")


def _snapshot_hierarchical_linkage(
    value: HierarchicalLinkageResult,
) -> HierarchicalLinkageSnapshot:
    for name in (
        "theme_correlation",
        "theme_beta",
        "r2",
        "incremental_theme_r2",
        "residual_mean",
        "residual_vol",
    ):
        _finite_optional(getattr(value, name), field_name=name)
    coefficients = tuple(
        sorted(
            (
                str(name),
                float(coefficient),
            )
            for name, coefficient in value.coefficients.items()
        )
    )
    if any(not isfinite(coefficient) for _, coefficient in coefficients):
        raise ValueError("linkage coefficient must be finite")
    return HierarchicalLinkageSnapshot(
        target=value.target.upper(),
        status=value.status,
        window=value.window,
        observations=value.observations,
        theme_correlation=value.theme_correlation,
        theme_beta=value.theme_beta,
        r2=value.r2,
        incremental_theme_r2=value.incremental_theme_r2,
        residual_mean=value.residual_mean,
        residual_vol=value.residual_vol,
        circularity_warning=value.circularity_warning,
        missing_controls=tuple(value.missing_controls),
        coefficients=coefficients,
        source_payload_hash=canonical_hash(asdict(value)),
    )


def _validate_simple_linkage(value: LinkageResult, ticker: str) -> LinkageResult:
    if value.ticker.upper() != ticker:
        raise ValueError("linkage ticker mismatch")
    for name in (
        "correlation",
        "beta",
        "r2",
        "residual_mean",
        "residual_vol",
        "beta_stability",
        "decoupling_score",
    ):
        _finite_optional(getattr(value, name), field_name=name)
    return value


def _linkage_status(
    linkage: LinkageResult | None,
    hierarchical: HierarchicalLinkageSnapshot | None,
) -> CompanyLinkageStatus:
    if linkage is None and hierarchical is None:
        return CompanyLinkageStatus.NOT_PROVIDED
    if (
        (linkage is not None and linkage.circularity_warning)
        or (
            hierarchical is not None
            and hierarchical.circularity_warning
        )
    ):
        return CompanyLinkageStatus.CIRCULARITY_WARNING
    if (
        hierarchical is not None
        and hierarchical.status == "ok"
    ):
        return CompanyLinkageStatus.USABLE
    if (
        linkage is not None
        and linkage.correlation is not None
        and linkage.beta is not None
        and linkage.r2 is not None
    ):
        return CompanyLinkageStatus.USABLE
    return CompanyLinkageStatus.COVERAGE_PENDING
~~~

Add:

~~~python
def _normalize_linkage_submissions(
    submissions: Sequence[CompanyLinkageSubmission],
    *,
    order: ResearchWorkOrder,
) -> dict[
    str,
    tuple[LinkageResult | None, HierarchicalLinkageSnapshot | None],
]:
    targets = {target.ticker for target in order.targets}
    output = {}
    for submission in submissions:
        ticker = submission.ticker.strip().upper()
        if ticker not in targets:
            raise ValueError("linkage target outside work order")
        if ticker in output:
            raise ValueError("duplicate company linkage submission")
        if (
            submission.linkage is None
            and submission.hierarchical_linkage is None
        ):
            raise ValueError("linkage submission is empty")

        simple = (
            None
            if submission.linkage is None
            else _validate_simple_linkage(
                submission.linkage,
                ticker,
            )
        )
        hierarchical = None
        if submission.hierarchical_linkage is not None:
            if submission.hierarchical_linkage.target.upper() != ticker:
                raise ValueError("linkage ticker mismatch")
            hierarchical = _snapshot_hierarchical_linkage(
                submission.hierarchical_linkage
            )
        output[ticker] = (simple, hierarchical)
    return output
~~~

Task 4 consumes this deterministic map to build company assessments.

- [ ] **Step 9: Run Task-3 tests and full regression**

Run:

~~~bash
pytest -q tests/test_research_execution.py
pytest -q
~~~

Expected: all company-normalization and linkage-snapshot helper tests PASS without any ResearchDossier implementation.

- [ ] **Step 10: Commit**

~~~bash
git add src/decision_lab/research_execution.py tests/test_research_execution.py
git commit -m "feat: add company research and linkage snapshots"
~~~

---

### Task 4: ResearchDossier coverage/status/hash, full acceptance, determinism, and public exports

**Files:**
- Modify: src/decision_lab/research_execution.py
- Modify: tests/test_research_execution.py
- Modify: src/decision_lab/__init__.py

**Interfaces:**
- Produces:
  - ResearchDossierStatus
  - ResearchDossier
  - build_research_dossier(...)

- [ ] **Step 1: Add RED status and complete-with-contradiction tests**

~~~python
from decision_lab.research_execution import (
    ResearchDossierStatus,
)


def test_empty_open_dossier_is_not_started():
    record = _unregistered_forced_archive()
    order = build_research_work_order(
        record,
        "UnknownRisk",
        ResearchMode.THEME_REASSESSMENT,
    )

    dossier = build_research_dossier(
        order,
        evidence_as_of="2026-09-20",
        closure=ResearchExecutionClosure.OPEN,
    )

    assert dossier.status is ResearchDossierStatus.NOT_STARTED
    assert dossier.unsatisfied_requirements == order.requirements


def test_partial_open_and_blocked_closed_are_distinct():
    record = _unregistered_forced_archive()
    order = build_research_work_order(
        record,
        "UnknownRisk",
        ResearchMode.THEME_REASSESSMENT,
    )
    evidence = _evidence(
        evidence_id="ev1",
        source_ref="official:risk",
        theme="UnknownRisk",
        payload={"theme_structure": "weak"},
        source_type="official_macro",
    )
    inputs = (
        ResearchEvidenceInput(
            evidence=evidence,
            independent=True,
            direction=ResearchEvidenceDirection.CONTRADICTING,
            dimensions=("theme_structure",),
            target_ticker=None,
        ),
    )

    partial = build_research_dossier(
        order,
        evidence_as_of="2026-09-20",
        closure=ResearchExecutionClosure.OPEN,
        evidence_inputs=inputs,
    )
    blocked = build_research_dossier(
        order,
        evidence_as_of="2026-09-20",
        closure=ResearchExecutionClosure.CLOSED,
        evidence_inputs=inputs,
    )

    assert partial.status is ResearchDossierStatus.PARTIAL
    assert blocked.status is ResearchDossierStatus.BLOCKED_INSUFFICIENT_EVIDENCE


def test_complete_theme_reassessment_can_still_be_contradictory_and_unresolved():
    record = _unregistered_forced_archive()
    policy = replace(
        ResearchWorkOrderPolicy(),
        minimum_independent_sources=1,
    )
    order = build_research_work_order(
        record,
        "UnknownRisk",
        ResearchMode.THEME_REASSESSMENT,
        policy=policy,
    )
    evidence = _evidence(
        evidence_id="ev1",
        source_ref="official:risk",
        theme="UnknownRisk",
        payload={"all": "covered"},
        source_type="official_macro",
    )
    dimensions = tuple(
        item.dimension for item in order.requirements
    )

    dossier = build_research_dossier(
        order,
        evidence_as_of="2026-09-20",
        closure=ResearchExecutionClosure.OPEN,
        evidence_inputs=(
            ResearchEvidenceInput(
                evidence=evidence,
                independent=True,
                direction=ResearchEvidenceDirection.CONTRADICTING,
                dimensions=dimensions,
                target_ticker=None,
            ),
        ),
        findings=(
            ResearchFinding(
                finding_id="unresolved",
                kind=ResearchFindingKind.UNRESOLVED,
                direction=None,
                dimension="theme_structure",
                target_ticker=None,
                statement="Cause remains unresolved.",
                evidence_source_hashes=(),
            ),
        ),
    )

    assert dossier.status is ResearchDossierStatus.COMPLETE
    assert dossier.contradictions_present
    assert dossier.unresolved_present
~~~

- [ ] **Step 2: Add RED company completion and linkage gate test**

Use a reduced policy to make a one-company acceptance concise while preserving exact semantics:

~~~python
def test_company_dossier_requires_normalized_dimension_independence_and_linkage():
    record, package = _registered_archive()
    policy = replace(
        ResearchWorkOrderPolicy(),
        industrials_company_dimensions=("growth",),
        minimum_independent_sources=1,
        minimum_independent_sources_per_company=1,
    )
    order = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
        policy=policy,
    )
    evidence = _evidence(
        evidence_id="aaa",
        source_ref="sec:aaa",
        ticker="AAA",
        payload={"revenue_growth": 0.2},
    )
    evidence_input = ResearchEvidenceInput(
        evidence=evidence,
        independent=True,
        direction=ResearchEvidenceDirection.SUPPORTING,
        dimensions=("growth",),
        target_ticker="AAA",
    )
    company = CompanyResearchSubmission(
        ticker="AAA",
        as_of="2026-09-20",
        adapter_name="industrials_infrastructure",
        raw_facts={"revenue_growth": 0.2},
        evidence_source_hashes=(evidence.source_hash,),
    )

    without_linkage = build_research_dossier(
        order,
        evidence_as_of="2026-09-20",
        closure=ResearchExecutionClosure.OPEN,
        evidence_inputs=(evidence_input,),
        company_submissions=(company,),
    )
    complete = build_research_dossier(
        order,
        evidence_as_of="2026-09-20",
        closure=ResearchExecutionClosure.OPEN,
        evidence_inputs=(evidence_input,),
        company_submissions=(company,),
        linkage_submissions=(
            CompanyLinkageSubmission(
                ticker="AAA",
                linkage=_usable_linkage(),
            ),
        ),
    )

    assert without_linkage.status is ResearchDossierStatus.PARTIAL
    assert complete.status is ResearchDossierStatus.COMPLETE
~~~

- [ ] **Step 3: Add RED determinism/work-order tamper/mutation tests**

~~~python
def test_tampered_work_order_is_rejected_by_dossier_builder():
    record = _unregistered_forced_archive()
    order = build_research_work_order(
        record,
        "UnknownRisk",
        ResearchMode.THEME_REASSESSMENT,
    )
    tampered = replace(
        order,
        minimum_independent_sources=999,
    )

    with pytest.raises(
        ValueError,
        match="invalid research work order",
    ):
        build_research_dossier(
            tampered,
            evidence_as_of="2026-09-20",
            closure=ResearchExecutionClosure.OPEN,
        )


def test_dossier_input_order_is_semantically_irrelevant():
    record = _unregistered_forced_archive()
    policy = replace(
        ResearchWorkOrderPolicy(),
        minimum_independent_sources=1,
    )
    order = build_research_work_order(
        record,
        "UnknownRisk",
        ResearchMode.THEME_REASSESSMENT,
        policy=policy,
    )
    first_evidence = _evidence(
        evidence_id="a",
        source_ref="official:a",
        theme="UnknownRisk",
        payload={"a": 1},
        source_type="official_macro",
    )
    second_evidence = _evidence(
        evidence_id="b",
        source_ref="industry:b",
        theme="UnknownRisk",
        payload={"b": 2},
        source_type="industry_primary",
    )
    dimensions = tuple(
        item.dimension for item in order.requirements
    )
    a = ResearchEvidenceInput(
        evidence=first_evidence,
        independent=True,
        direction=ResearchEvidenceDirection.SUPPORTING,
        dimensions=dimensions[:2],
        target_ticker=None,
    )
    b = ResearchEvidenceInput(
        evidence=second_evidence,
        independent=True,
        direction=ResearchEvidenceDirection.CONTRADICTING,
        dimensions=dimensions[2:],
        target_ticker=None,
    )

    first = build_research_dossier(
        order,
        evidence_as_of="2026-09-20T23:00:00+00:00",
        closure=ResearchExecutionClosure.OPEN,
        evidence_inputs=(a, b),
    )
    second = build_research_dossier(
        order,
        evidence_as_of="2026-09-20T19:00:00-04:00",
        closure=ResearchExecutionClosure.OPEN,
        evidence_inputs=(b, a),
    )

    assert first == second
    assert first.input_hash == second.input_hash
    assert first.dossier_hash == second.dossier_hash
~~~

- [ ] **Step 4: Implement ResearchDossier types/constants**

Add:

~~~python
class ResearchDossierStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    BLOCKED_INSUFFICIENT_EVIDENCE = "BLOCKED_INSUFFICIENT_EVIDENCE"


_DOSSIER_LIMITATIONS = (
    "research completion means required coverage, not thesis correctness",
    "allocation tier does not prove research execution without a dossier",
    "provider retrieval and extraction occur outside this module",
    "theme package exact historical bytes are not recoverable from ReplayCycleResult alone",
    "research dossier does not grant trading permission",
    "evidence payload content is committed by hash but not embedded in the dossier",
)


@dataclass(frozen=True)
class ResearchDossier:
    schema_version: str
    work_order_hash: str
    source_archive_record_hash: str
    source_cycle_as_of: str
    theme_id: str
    research_mode: ResearchMode
    evidence_as_of: str
    closure: ResearchExecutionClosure
    status: ResearchDossierStatus
    evidence_bindings: tuple[ResearchEvidenceBinding, ...]
    independent_source_count: int
    satisfied_requirements: tuple[ResearchRequirement, ...]
    unsatisfied_requirements: tuple[ResearchRequirement, ...]
    company_assessments: tuple[CompanyResearchAssessment, ...]
    findings: tuple[ResearchFinding, ...]
    contradictions_present: bool
    unresolved_present: bool
    limitations: tuple[str, ...]
    input_hash: str
    dossier_hash: str
~~~

- [ ] **Step 5: Implement linkage map and company-assessment composition**

Add deterministic _normalize_linkage_submissions and then:

~~~python
def _build_company_assessments(
    *,
    order: ResearchWorkOrder,
    bindings: tuple[ResearchEvidenceBinding, ...],
    company_snapshots: Mapping[str, NormalizedCompanySnapshot],
    linkage_map,
) -> tuple[CompanyResearchAssessment, ...]:
    rows: list[CompanyResearchAssessment] = []
    for target in order.targets:
        ticker = target.ticker
        linkage, hierarchical = linkage_map.get(
            ticker,
            (None, None),
        )
        status = _linkage_status(linkage, hierarchical)
        independent_refs = {
            item.evidence.source_ref
            for item in bindings
            if item.target_ticker == ticker and item.independent
        }
        normalized = company_snapshots.get(ticker)
        covered_dimensions = (
            ()
            if normalized is None
            else tuple(field.name for field in normalized.fields)
        )
        evidence_hashes = tuple(
            sorted(
                item.evidence.source_hash
                for item in bindings
                if item.target_ticker == ticker
            )
        )
        cautions: list[str] = []
        if status is CompanyLinkageStatus.COVERAGE_PENDING:
            cautions.append("linkage coverage pending")
        elif status is CompanyLinkageStatus.CIRCULARITY_WARNING:
            cautions.append("linkage circularity warning")
        if (
            len(independent_refs)
            < order.minimum_independent_sources_per_company
        ):
            cautions.append("independent source minimum not met")

        rows.append(
            CompanyResearchAssessment(
                ticker=ticker,
                normalized_evidence=normalized,
                evidence_source_hashes=evidence_hashes,
                independent_source_count=len(independent_refs),
                covered_dimensions=covered_dimensions,
                linkage_status=status,
                linkage=linkage,
                hierarchical_linkage=hierarchical,
                cautions=tuple(cautions),
            )
        )
    return tuple(rows)
~~~

- [ ] **Step 6: Implement requirement coverage and status derivation**

~~~python
def _requirement_satisfied(
    requirement: ResearchRequirement,
    *,
    bindings: tuple[ResearchEvidenceBinding, ...],
    assessments: Mapping[str, CompanyResearchAssessment],
) -> bool:
    if requirement.scope is ResearchRequirementScope.THEME_EVIDENCE:
        return any(
            item.target_ticker is None
            and requirement.dimension in item.dimensions
            for item in bindings
        )

    assert requirement.target_ticker is not None
    assessment = assessments[requirement.target_ticker]
    if requirement.scope is ResearchRequirementScope.COMPANY_LINKAGE:
        return assessment.linkage_status is CompanyLinkageStatus.USABLE

    binding_coverage = any(
        item.target_ticker == requirement.target_ticker
        and requirement.dimension in item.dimensions
        for item in bindings
    )
    normalized_coverage = (
        assessment.normalized_evidence is not None
        and requirement.dimension in assessment.covered_dimensions
    )
    return binding_coverage and normalized_coverage


def _derive_status(
    *,
    complete: bool,
    closure: ResearchExecutionClosure,
    evidence_bindings,
    company_submissions,
    linkage_submissions,
    findings,
) -> ResearchDossierStatus:
    if complete:
        return ResearchDossierStatus.COMPLETE
    if closure is ResearchExecutionClosure.CLOSED:
        return ResearchDossierStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    if not (
        evidence_bindings
        or company_submissions
        or linkage_submissions
        or findings
    ):
        return ResearchDossierStatus.NOT_STARTED
    return ResearchDossierStatus.PARTIAL
~~~

- [ ] **Step 7: Implement build_research_dossier hashing and final composition**

~~~python
def _dossier_payload_without_hash(
    dossier: ResearchDossier,
) -> dict[str, object]:
    payload = asdict(dossier)
    payload.pop("dossier_hash")
    return payload


def build_research_dossier(
    work_order: ResearchWorkOrder,
    *,
    evidence_as_of: str,
    closure: ResearchExecutionClosure,
    evidence_inputs: Sequence[ResearchEvidenceInput] = (),
    company_submissions: Sequence[CompanyResearchSubmission] = (),
    linkage_submissions: Sequence[CompanyLinkageSubmission] = (),
    findings: Sequence[ResearchFinding] = (),
) -> ResearchDossier:
    _validate_work_order_hash(work_order)
    if not isinstance(closure, ResearchExecutionClosure):
        raise TypeError("unsupported research execution closure")
    evidence_as_of_dt = _parse_utc(evidence_as_of)

    bindings, originals = _freeze_evidence_inputs(
        evidence_inputs,
        order=work_order,
        evidence_as_of=evidence_as_of_dt,
    )
    canonical_findings = _normalize_findings(
        findings,
        order=work_order,
        evidence=originals,
    )
    company_snapshots = _normalize_company_submissions(
        company_submissions,
        order=work_order,
        evidence=originals,
        evidence_as_of=evidence_as_of_dt,
    )
    linkage_map = _normalize_linkage_submissions(
        linkage_submissions,
        order=work_order,
    )
    assessments = _build_company_assessments(
        order=work_order,
        bindings=bindings,
        company_snapshots=company_snapshots,
        linkage_map=linkage_map,
    )
    assessment_by_ticker = {
        item.ticker: item for item in assessments
    }

    satisfied = tuple(
        item
        for item in work_order.requirements
        if _requirement_satisfied(
            item,
            bindings=bindings,
            assessments=assessment_by_ticker,
        )
    )
    unsatisfied = tuple(
        item
        for item in work_order.requirements
        if item not in set(satisfied)
    )

    independent_refs = {
        item.evidence.source_ref
        for item in bindings
        if item.independent
    }
    company_complete = (
        work_order.research_mode is ResearchMode.THEME_REASSESSMENT
        or all(
            item.normalized_evidence is not None
            and item.independent_source_count
                >= work_order.minimum_independent_sources_per_company
            for item in assessments
        )
    )
    complete = (
        not unsatisfied
        and len(independent_refs)
            >= work_order.minimum_independent_sources
        and company_complete
    )
    status = _derive_status(
        complete=complete,
        closure=closure,
        evidence_bindings=bindings,
        company_submissions=company_submissions,
        linkage_submissions=linkage_submissions,
        findings=canonical_findings,
    )
    contradictions_present = any(
        item.direction is ResearchEvidenceDirection.CONTRADICTING
        for item in bindings
    ) or any(
        item.kind is not ResearchFindingKind.UNRESOLVED
        and item.direction is ResearchEvidenceDirection.CONTRADICTING
        for item in canonical_findings
    )
    unresolved_present = any(
        item.kind is ResearchFindingKind.UNRESOLVED
        for item in canonical_findings
    )

    canonical_evidence_as_of = evidence_as_of_dt.isoformat()
    input_payload = {
        "work_order_hash": work_order.work_order_hash,
        "evidence_as_of": canonical_evidence_as_of,
        "closure": closure,
        "evidence_bindings": [asdict(item) for item in bindings],
        "company_submissions": [
            {
                "ticker": item.ticker.strip().upper(),
                "as_of": _parse_utc(item.as_of).isoformat(),
                "adapter_name": item.adapter_name,
                "raw_facts": _canonical_raw_facts(item.raw_facts),
                "evidence_source_hashes": sorted(
                    item.evidence_source_hashes
                ),
            }
            for item in sorted(
                company_submissions,
                key=lambda item: item.ticker.upper(),
            )
        ],
        "linkage_submissions": [
            _linkage_input_payload(item)
            for item in sorted(
                linkage_submissions,
                key=lambda item: item.ticker.upper(),
            )
        ],
        "findings": [asdict(item) for item in canonical_findings],
    }
    input_hash = canonical_hash(input_payload)

    seed = ResearchDossier(
        schema_version=SCHEMA_VERSION,
        work_order_hash=work_order.work_order_hash,
        source_archive_record_hash=work_order.source_archive_record_hash,
        source_cycle_as_of=work_order.source_cycle_as_of,
        theme_id=work_order.theme_id,
        research_mode=work_order.research_mode,
        evidence_as_of=canonical_evidence_as_of,
        closure=closure,
        status=status,
        evidence_bindings=bindings,
        independent_source_count=len(independent_refs),
        satisfied_requirements=satisfied,
        unsatisfied_requirements=unsatisfied,
        company_assessments=assessments,
        findings=canonical_findings,
        contradictions_present=contradictions_present,
        unresolved_present=unresolved_present,
        limitations=_DOSSIER_LIMITATIONS,
        input_hash=input_hash,
        dossier_hash="0" * 64,
    )
    return replace(
        seed,
        dossier_hash=canonical_hash(
            _dossier_payload_without_hash(seed)
        ),
    )
~~~

Define _linkage_input_payload using only validated/canonical simple linkage asdict and hierarchical snapshot asdict so mapping insertion order cannot affect input_hash.

- [ ] **Step 8: Add public import RED test, then export all Increment-8 symbols**

Add:

~~~python
def test_research_execution_interfaces_are_publicly_importable():
    import decision_lab

    for name in (
        "ResearchMode",
        "ResearchAuthorization",
        "ResearchRequirementScope",
        "ResearchRequirement",
        "ResearchTarget",
        "ResearchWorkOrderPolicy",
        "ResearchWorkOrder",
        "ResearchEvidenceDirection",
        "ResearchEvidenceInput",
        "FrozenResearchEvidence",
        "ResearchEvidenceBinding",
        "CompanyResearchSubmission",
        "NormalizedCompanyField",
        "NormalizedCompanySnapshot",
        "CompanyLinkageSubmission",
        "HierarchicalLinkageSnapshot",
        "CompanyLinkageStatus",
        "CompanyResearchAssessment",
        "ResearchFindingKind",
        "ResearchFinding",
        "ResearchExecutionClosure",
        "ResearchDossierStatus",
        "ResearchDossier",
        "build_research_work_order",
        "build_research_dossier",
    ):
        assert getattr(decision_lab, name) is not None
~~~

Run this test and verify RED before modifying __init__.py.

Then import/export those 25 symbols in src/decision_lab/__init__.py and keep __all__ sorted according to the repository's existing convention.

- [ ] **Step 9: Add real DataCenter/Genomics acceptance using existing theme packages**

Use load_theme_package for:

- config/themes/datacenter_infra.yaml
- config/themes/genomics_bio.yaml

For each package, create a registered source replay with a coverage-pending market batch plus one strong independent external observation, select one effective universe ticker, build COMPANY_DEEP_DIVE, and assert:

~~~python
def test_real_theme_packages_generate_domain_specific_company_requirements():
    # Build both historical replay records with their real ThemePackage.
    # Use explicit target chosen from package.universe.active_candidates("2026-09-19").
    dc_order = ...
    bio_order = ...

    assert dc_order.evidence_adapter == "industrials_infrastructure"
    assert bio_order.evidence_adapter == "biotech_clinical"

    dc_dimensions = {
        item.dimension
        for item in dc_order.requirements
        if item.scope is ResearchRequirementScope.COMPANY_EVIDENCE
    }
    bio_dimensions = {
        item.dimension
        for item in bio_order.requirements
        if item.scope is ResearchRequirementScope.COMPANY_EVIDENCE
    }

    assert "order_or_contract_visibility" in dc_dimensions
    assert "clinical_phase" in bio_dimensions
    assert "order_or_contract_visibility" not in bio_dimensions
    assert "clinical_phase" not in dc_dimensions
~~~

Do not use network data; all bars/evidence are synthetic/public-safe fixtures.

- [ ] **Step 10: Run Task-4 tests and full regression**

Run:

~~~bash
pytest -q tests/test_research_execution.py
pytest -q
~~~

Expected: PASS.

- [ ] **Step 11: Commit**

~~~bash
git add src/decision_lab/research_execution.py src/decision_lab/__init__.py tests/test_research_execution.py
git commit -m "feat: build deterministic research dossiers"
~~~

---

### Task 5: Final safety gaps, immutable-state audit, purity/Ruff, whole-branch review

**Files:**
- Verify: src/decision_lab/research_execution.py
- Verify: src/decision_lab/__init__.py
- Verify: tests/test_research_execution.py
- Review-only: all forbidden downstream modules.

**Interfaces:**
- Verification evidence only.

- [ ] **Step 1: Add final RED tests for Review Focus edge cases**

Add:

~~~python
def test_conflicting_source_metadata_is_rejected():
    order = _company_order()
    first = _evidence(
        evidence_id="a",
        source_ref="same-source",
        ticker="AAA",
        payload={"revenue_growth": 0.2},
        source_type="sec_filing",
    )
    second = _evidence(
        evidence_id="b",
        source_ref="same-source",
        ticker="AAA",
        payload={"gross_margin": 0.3},
        source_type="company_ir",
    )

    with pytest.raises(
        ValueError,
        match="conflicting research source metadata",
    ):
        build_research_dossier(
            order,
            evidence_as_of="2026-09-20",
            closure=ResearchExecutionClosure.OPEN,
            evidence_inputs=(
                ResearchEvidenceInput(
                    first,
                    True,
                    ResearchEvidenceDirection.SUPPORTING,
                    ("growth",),
                    "AAA",
                ),
                ResearchEvidenceInput(
                    second,
                    True,
                    ResearchEvidenceDirection.SUPPORTING,
                    ("margin_quality",),
                    "AAA",
                ),
            ),
        )


def test_company_raw_facts_and_hierarchical_coefficients_do_not_leak_mutability():
    order = _company_order()
    evidence = _evidence(
        evidence_id="aaa",
        source_ref="sec:aaa",
        ticker="AAA",
        payload={"revenue_growth": 0.2},
    )
    raw_facts = {"revenue_growth": 0.2}
    coefficients = {"SPY": 0.4, "WorkTheme": 0.6}
    hierarchical = HierarchicalLinkageResult(
        target="AAA",
        status="ok",
        window=63,
        observations=63,
        theme_correlation=0.6,
        theme_beta=0.6,
        r2=0.5,
        incremental_theme_r2=0.2,
        residual_mean=0.0,
        residual_vol=0.02,
        circularity_warning=False,
        missing_controls=(),
        coefficients=coefficients,
    )
    dossier = build_research_dossier(
        order,
        evidence_as_of="2026-09-20",
        closure=ResearchExecutionClosure.OPEN,
        evidence_inputs=(
            ResearchEvidenceInput(
                evidence,
                True,
                ResearchEvidenceDirection.SUPPORTING,
                ("growth",),
                "AAA",
            ),
        ),
        company_submissions=(
            CompanyResearchSubmission(
                "AAA",
                "2026-09-20",
                "industrials_infrastructure",
                raw_facts,
                (evidence.source_hash,),
            ),
        ),
        linkage_submissions=(
            CompanyLinkageSubmission(
                "AAA",
                hierarchical_linkage=hierarchical,
            ),
        ),
    )
    before = dossier

    raw_facts["revenue_growth"] = 9.9
    coefficients["SPY"] = 9.9
    evidence.payload["revenue_growth"] = 9.9

    assert dossier == before


def test_non_finite_linkage_is_rejected():
    order = _company_order()
    bad = replace(_usable_linkage(), beta=float("nan"))

    with pytest.raises(ValueError, match="must be finite"):
        build_research_dossier(
            order,
            evidence_as_of="2026-09-20",
            closure=ResearchExecutionClosure.OPEN,
            linkage_submissions=(
                CompanyLinkageSubmission(
                    ticker="AAA",
                    linkage=bad,
                ),
            ),
        )


def test_company_submission_timestamp_before_source_cycle_is_rejected():
    order = _company_order()
    evidence = _evidence(
        evidence_id="aaa",
        source_ref="sec:aaa",
        ticker="AAA",
        payload={"revenue_growth": 0.2},
    )

    with pytest.raises(
        ValueError,
        match="company research as_of is outside execution window",
    ):
        build_research_dossier(
            order,
            evidence_as_of="2026-09-20",
            closure=ResearchExecutionClosure.OPEN,
            evidence_inputs=(
                ResearchEvidenceInput(
                    evidence,
                    True,
                    ResearchEvidenceDirection.SUPPORTING,
                    ("growth",),
                    "AAA",
                ),
            ),
            company_submissions=(
                CompanyResearchSubmission(
                    "AAA",
                    "2026-09-18",
                    "industrials_infrastructure",
                    {"revenue_growth": 0.2},
                    (evidence.source_hash,),
                ),
            ),
        )
~~~

Any RED here receives one minimal fix pass in the owning helper.

- [ ] **Step 2: Run fresh full regression**

~~~bash
pytest -q
~~~

Expected: all tests PASS.

- [ ] **Step 3: Run changed-files Ruff**

~~~bash
python -m ruff check \
  src/decision_lab/research_execution.py \
  src/decision_lab/__init__.py \
  tests/test_research_execution.py
~~~

Expected: exit 0.

- [ ] **Step 4: Audit forbidden semantic drift and prohibited dependencies**

Verify no diffs to:

~~~text
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
~~~

Verify final PR contains no persistent new .github/workflows file.

Verify research_execution.py contains no imports/calls for:

~~~text
pathlib
os
json file I/O
requests
urllib
httpx
yfinance
alpaca
polygon
subprocess
socket
datetime.now
time.time
random
uuid
make_evidence
assess_tape_state
route_playbooks
compile_decision
write_immutable_json
~~~

Verify public dataclasses contain no fields named:

~~~text
company_score
conviction_score
trade_permission
entry
invalidation
position_size
order
alpha
return
accuracy
performance_score
~~~

- [ ] **Step 5: Whole-branch review against Review Focus**

Inspect specifically:

- source replay validation occurs through public cohort evaluator before authorization;
- eligible routing states are exact and capacity-missed cannot bypass allocator;
- unregistered forced review stays SCAN_ONLY and theme-only;
- package versions are checked against source market diagnostics;
- exact package bytes are never claimed recoverable;
- target candidates are source-cycle effective and caller-explicit;
- policy dimension order is canonicalized;
- work_order_hash is recomputed before dossier use;
- EvidenceRecord source_hash is recomputed, not trusted;
- payload hashes bind evidence content without embedding mutable payload;
- model/inferred evidence cannot be marked independent;
- source_ref independence/source_type conflicts fail closed;
- evidence temporal fields cannot exceed evidence_as_of;
- company raw facts require same-ticker cited support with type-sensitive equality;
- normalized company requirement coverage needs both binding and non-None normalized field;
- generic adapter cannot create company deep dive;
- linkage pending/circularity does not satisfy linkage requirement;
- original mutable raw_facts/payload/coefficients cannot mutate output;
- observed synthesis cannot cite non-observed evidence;
- unresolved findings require direction None;
- COMPLETE can coexist with contradiction/unresolved;
- CLOSED incomplete state becomes BLOCKED_INSUFFICIENT_EVIDENCE, not a thesis verdict;
- no Tape/Playbook/Decision imports or semantics;
- input/output hashes are order-independent and free of ambient timestamps.

Any Critical/Important issue gets one TDD fix pass:

1. write reproducing RED test;
2. verify RED;
3. implement minimal fix;
4. rerun targeted test;
5. rerun full suite and Ruff.

- [ ] **Step 6: Exact-final-tree verification**

On the exact final branch head:

~~~bash
pytest -q
python -m ruff check \
  src/decision_lab/research_execution.py \
  src/decision_lab/__init__.py \
  tests/test_research_execution.py
~~~

Record exact pytest count/time and Ruff result.

- [ ] **Step 7: Keep branch unmerged**

Present integration options only after exact-final-tree verification. Do not merge until explicit user authorization.
