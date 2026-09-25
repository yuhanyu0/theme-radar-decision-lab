from dataclasses import asdict, replace

import pytest

from decision_lab.evidence import EvidenceRecord
from decision_lab.ledger import canonical_hash
from decision_lab.market_observation import (
    MarketBar,
    MarketObservationConfig,
    MarketObservationMode,
    MarketObservationSpec,
)
from decision_lab.replay import ReplayCycleInput, ThemeReplayInput, run_replay_cycle
from decision_lab.replay_archive import build_replay_archive_record
from decision_lab.research_budget import ResearchBudgetConfig
from decision_lab.research_execution import (
    ResearchEvidenceDirection,
    ResearchEvidenceInput,
    ResearchExecutionClosure,
    ResearchMode,
    ResearchWorkOrderPolicy,
    build_research_dossier,
    build_research_work_order,
)
from decision_lab.research_execution_archive import (
    build_research_dossier_archive_record,
    build_research_work_order_archive_record,
)
from decision_lab.research_progression import evaluate_research_progression
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


def _package(theme="ProgressionTheme"):
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


def _source_observation(theme):
    return ThemeScanObservation(
        theme_id=theme,
        as_of="2026-09-19",
        source_type="derived_feature",
        source_ref=f"fixture:{theme}:contradiction",
        discovery_signal=1.0,
        structure_signal=1.0,
        persistence_signal=1.0,
        breadth_signal=1.0,
        relative_strength_signal=1.0,
        novelty_signal=1.0,
        support_direction=SupportDirection.CONTRADICTING,
        evidence_refs=(f"fixture:{theme}",),
        is_independent=True,
        observed_or_inferred="observed",
    )


def _work_order_archive(*, minimum_independent_sources=1):
    package = _package()
    theme = package.definition.theme_id
    replay = run_replay_cycle(
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
                        version="progression-test",
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
                    market_source_ref="fixture:progression-market",
                ),
            ),
            external_observations=(_source_observation(theme),),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
    replay_archive = build_replay_archive_record(replay)
    raw_policy = replace(
        ResearchWorkOrderPolicy(),
        minimum_independent_sources=minimum_independent_sources,
    )
    policy = replace(
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
    order = build_research_work_order(
        replay_archive,
        theme,
        ResearchMode.THEME_REASSESSMENT,
        theme_package=package,
        policy=policy,
    )
    archive = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    return archive, order


def _evidence(*, evidence_as_of, suffix):
    raw = EvidenceRecord(
        evidence_id=f"ev:{suffix}",
        observed_at=evidence_as_of,
        retrieved_at=evidence_as_of,
        market_asof=None,
        ticker=None,
        theme="ProgressionTheme",
        source_type="official_macro",
        source_ref=f"official:{suffix}",
        fact_type="progression_fact",
        payload={"state": suffix},
        is_observed_fact=True,
    )
    return raw.with_hash()


def _dossier(
    order,
    *,
    evidence_as_of,
    include_all_requirements=True,
    closure=ResearchExecutionClosure.OPEN,
):
    evidence = _evidence(
        evidence_as_of=evidence_as_of,
        suffix=evidence_as_of,
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


def _root(
    *,
    evidence_as_of="2026-09-20T20:00:00+00:00",
    minimum_independent_sources=1,
):
    work_archive, order = _work_order_archive(
        minimum_independent_sources=minimum_independent_sources
    )
    record = build_research_dossier_archive_record(
        work_archive,
        _dossier(order, evidence_as_of=evidence_as_of),
    )
    return work_archive, order, record


def _child(
    work_archive,
    order,
    parent,
    *,
    evidence_as_of="2026-09-21T20:00:00+00:00",
):
    return build_research_dossier_archive_record(
        work_archive,
        _dossier(order, evidence_as_of=evidence_as_of),
        prior_dossier_archive=parent,
    )


def _with_parent_hash(record, parent_hash):
    seed = replace(
        record,
        prior_dossier_archive_record_hash=parent_hash,
        archive_record_hash="0" * 64,
    )
    payload = asdict(seed)
    payload.pop("archive_record_hash")
    return replace(
        seed,
        archive_record_hash=canonical_hash(payload),
    )


def test_progression_rejects_empty_input():
    with pytest.raises(ValueError, match="non-empty"):
        evaluate_research_progression(())


def test_progression_rejects_duplicate_archive_identity():
    _, _, root = _root()

    with pytest.raises(ValueError, match="duplicate"):
        evaluate_research_progression((root, root))


def test_progression_rejects_mixed_exact_work_order_archive_identity():
    _, _, first = _root(minimum_independent_sources=1)
    _, _, second = _root(
        evidence_as_of="2026-09-20T21:00:00+00:00",
        minimum_independent_sources=2,
    )

    assert (
        first.work_order_archive.archive_record_hash
        != second.work_order_archive.archive_record_hash
    )
    with pytest.raises(ValueError, match="work order"):
        evaluate_research_progression((first, second))


def test_progression_rejects_semantically_invalid_archive_record():
    _, _, root = _root()
    tampered = replace(root, archive_record_hash="0" * 64)

    with pytest.raises(ValueError):
        evaluate_research_progression((tampered,))


def test_single_root_is_root_and_leaf_without_transition():
    _, _, root = _root()

    report = evaluate_research_progression((root,))

    assert report.roots == (root.archive_record_hash,)
    assert report.orphans == ()
    assert report.forks == ()
    assert report.leaves == (root.archive_record_hash,)
    assert report.transitions == ()
    assert len(report.snapshots) == 1


def test_linear_parent_chain_reconstructs_resolved_transition():
    work_archive, order, root = _root()
    child = _child(work_archive, order, root)

    report = evaluate_research_progression((child, root))

    assert report.roots == (root.archive_record_hash,)
    assert report.leaves == (child.archive_record_hash,)
    assert len(report.transitions) == 1
    transition = report.transitions[0]
    assert transition.parent_archive_record_hash == root.archive_record_hash
    assert transition.child_archive_record_hash == child.archive_record_hash


def test_missing_parent_is_orphan_not_root():
    work_archive, order, root = _root()
    child = _child(work_archive, order, root)

    report = evaluate_research_progression((child,))

    assert report.roots == ()
    assert len(report.orphans) == 1
    orphan = report.orphans[0]
    assert orphan.child_archive_record_hash == child.archive_record_hash
    assert (
        orphan.missing_parent_archive_record_hash
        == root.archive_record_hash
    )
    assert report.leaves == (child.archive_record_hash,)


def test_fork_is_reported_without_selecting_a_child():
    work_archive, order, root = _root()
    child_a = _child(
        work_archive,
        order,
        root,
        evidence_as_of="2026-09-21T20:00:00+00:00",
    )
    child_b = _child(
        work_archive,
        order,
        root,
        evidence_as_of="2026-09-22T20:00:00+00:00",
    )

    report = evaluate_research_progression((child_b, root, child_a))

    assert len(report.forks) == 1
    fork = report.forks[0]
    assert fork.parent_archive_record_hash == root.archive_record_hash
    assert fork.child_archive_record_hashes == tuple(
        sorted(
            (
                child_a.archive_record_hash,
                child_b.archive_record_hash,
            )
        )
    )
    assert report.leaves == tuple(
        sorted(
            (
                child_a.archive_record_hash,
                child_b.archive_record_hash,
            )
        )
    )


def test_resolved_parent_must_be_strictly_earlier():
    work_archive, order, parent = _root(
        evidence_as_of="2026-09-21T20:00:00+00:00"
    )
    _, _, standalone_child = _root(
        evidence_as_of="2026-09-20T20:00:00+00:00"
    )
    assert standalone_child.work_order_archive == work_archive
    child = _with_parent_hash(
        standalone_child,
        parent.archive_record_hash,
    )

    with pytest.raises(ValueError, match="strictly earlier"):
        evaluate_research_progression((parent, child))


def test_input_permutation_has_identical_report_and_hash():
    work_archive, order, root = _root()
    child = _child(work_archive, order, root)

    first = evaluate_research_progression((root, child))
    second = evaluate_research_progression((child, root))

    assert first == second
    assert first.progression_report_hash == second.progression_report_hash
