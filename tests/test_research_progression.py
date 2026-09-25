from dataclasses import asdict, fields, replace

import pytest

from decision_lab.evidence import EvidenceRecord
from decision_lab.ledger import canonical_hash
from decision_lab.linkage import LinkageResult
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
    CompanyLinkageStatus,
    CompanyResearchSubmission,
    ResearchDossierStatus,
    ResearchEvidenceDirection,
    ResearchEvidenceInput,
    ResearchExecutionClosure,
    ResearchFinding,
    ResearchFindingKind,
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



def _theme_archive_record(
    work_archive,
    order,
    *,
    evidence_as_of,
    dimensions,
    direction=ResearchEvidenceDirection.SUPPORTING,
    closure=ResearchExecutionClosure.OPEN,
    finding_id=None,
    finding_statement=None,
    unresolved=False,
    parent=None,
):
    evidence = _evidence(
        evidence_as_of=evidence_as_of,
        suffix=f"{evidence_as_of}:{direction.value}",
    )
    findings = ()
    if unresolved:
        findings = (
            ResearchFinding(
                finding_id=finding_id or f"unresolved:{evidence_as_of}",
                kind=ResearchFindingKind.UNRESOLVED,
                direction=None,
                dimension=dimensions[0],
                target_ticker=None,
                statement=finding_statement or "open question remains",
                evidence_source_hashes=(),
            ),
        )
    elif finding_id is not None:
        findings = (
            ResearchFinding(
                finding_id=finding_id,
                kind=ResearchFindingKind.OBSERVED_SYNTHESIS,
                direction=direction,
                dimension=dimensions[0],
                target_ticker=None,
                statement=finding_statement or "observed synthesis",
                evidence_source_hashes=(evidence.source_hash,),
            ),
        )
    dossier = build_research_dossier(
        order,
        evidence_as_of=evidence_as_of,
        closure=closure,
        evidence_inputs=(
            ResearchEvidenceInput(
                evidence=evidence,
                independent=True,
                direction=direction,
                dimensions=tuple(dimensions),
                target_ticker=None,
            ),
        ),
        findings=findings,
    )
    return build_research_dossier_archive_record(
        work_archive,
        dossier,
        prior_dossier_archive=parent,
    )


def _company_work_order_archive():
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
                        version="progression-company-test",
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
                    market_source_ref="fixture:progression-company-market",
                ),
            ),
            external_observations=(
                ThemeScanObservation(
                    theme_id=theme,
                    as_of="2026-09-19",
                    source_type="derived_feature",
                    source_ref=f"fixture:{theme}:support",
                    discovery_signal=1.0,
                    structure_signal=1.0,
                    persistence_signal=1.0,
                    breadth_signal=1.0,
                    relative_strength_signal=1.0,
                    novelty_signal=1.0,
                    support_direction=SupportDirection.SUPPORTING,
                    evidence_refs=(f"fixture:{theme}:support",),
                    is_independent=True,
                    observed_or_inferred="observed",
                ),
            ),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
    replay_archive = build_replay_archive_record(replay)
    raw_policy = replace(
        ResearchWorkOrderPolicy(),
        industrials_company_dimensions=("growth",),
        minimum_independent_sources=1,
        minimum_independent_sources_per_company=2,
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
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
        policy=policy,
    )
    return (
        build_research_work_order_archive_record(
            replay_archive,
            order,
            work_order_policy=policy,
        ),
        order,
    )


def _company_burden_record():
    work_archive, order = _company_work_order_archive()
    raw = EvidenceRecord(
        evidence_id="ev:company-burden",
        observed_at="2026-09-20T20:00:00+00:00",
        retrieved_at="2026-09-20T20:00:00+00:00",
        market_asof=None,
        ticker="AAA",
        theme="ProgressionTheme",
        source_type="sec_filing",
        source_ref="sec:AAA:burden",
        fact_type="company_progression_fact",
        payload={"revenue_growth": 0.2},
        is_observed_fact=True,
    )
    evidence = raw.with_hash()
    dossier = build_research_dossier(
        order,
        evidence_as_of="2026-09-20T21:00:00+00:00",
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
                as_of="2026-09-20T20:30:00+00:00",
                adapter_name="industrials_infrastructure",
                raw_facts={"revenue_growth": 0.2},
                evidence_source_hashes=(evidence.source_hash,),
            ),
        ),
    )
    record = build_research_dossier_archive_record(
        work_archive,
        dossier,
    )
    return record


def test_transition_reports_open_to_closed_separately_from_complete():
    work_archive, order = _work_order_archive()
    all_dimensions = tuple(item.dimension for item in order.requirements)
    parent = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        dimensions=all_dimensions,
        closure=ResearchExecutionClosure.OPEN,
    )
    child = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        dimensions=all_dimensions,
        closure=ResearchExecutionClosure.CLOSED,
        parent=parent,
    )

    report = evaluate_research_progression((parent, child))
    transition = report.transitions[0]

    assert transition.closure_transition.value == "OPEN_TO_CLOSED"
    assert transition.parent_status is ResearchDossierStatus.COMPLETE
    assert transition.child_status is ResearchDossierStatus.COMPLETE
    assert not transition.became_complete
    assert not transition.lost_complete_status
    assert transition.elapsed_seconds == 86400.0


def test_transition_reports_closed_to_open_as_execution_reopening():
    work_archive, order = _work_order_archive()
    all_dimensions = tuple(item.dimension for item in order.requirements)
    parent = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        dimensions=all_dimensions,
        closure=ResearchExecutionClosure.CLOSED,
    )
    child = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        dimensions=(order.requirements[0].dimension,),
        closure=ResearchExecutionClosure.OPEN,
        parent=parent,
    )

    transition = evaluate_research_progression(
        (parent, child)
    ).transitions[0]

    assert transition.closure_transition.value == "CLOSED_TO_OPEN"
    assert transition.parent_status is ResearchDossierStatus.COMPLETE
    assert transition.child_status is ResearchDossierStatus.PARTIAL
    assert transition.lost_complete_status


def test_transition_reports_requirement_progress_and_regression():
    work_archive, order = _work_order_archive()
    first = order.requirements[0]
    remaining = tuple(order.requirements[1:])
    parent = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        dimensions=(first.dimension,),
    )
    child = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        dimensions=tuple(item.dimension for item in order.requirements),
        parent=parent,
    )

    forward = evaluate_research_progression(
        (parent, child)
    ).transitions[0]

    assert forward.newly_satisfied_requirements == remaining
    assert forward.newly_unsatisfied_requirements == ()
    assert forward.still_satisfied_requirements == (first,)
    assert forward.still_unsatisfied_requirements == ()
    assert forward.became_complete
    assert not forward.lost_complete_status

    regressed = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-22T20:00:00+00:00",
        dimensions=(first.dimension,),
        parent=child,
    )
    backward = evaluate_research_progression(
        (child, regressed)
    ).transitions[0]

    assert backward.newly_satisfied_requirements == ()
    assert backward.newly_unsatisfied_requirements == remaining
    assert backward.still_satisfied_requirements == (first,)
    assert backward.still_unsatisfied_requirements == ()
    assert not backward.became_complete
    assert backward.lost_complete_status


def test_transition_reports_added_and_removed_evidence_hashes():
    work_archive, order = _work_order_archive()
    parent = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        dimensions=(order.requirements[0].dimension,),
    )
    child = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        dimensions=(order.requirements[0].dimension,),
        parent=parent,
    )

    transition = evaluate_research_progression(
        (parent, child)
    ).transitions[0]
    parent_hash = parent.dossier.evidence_bindings[0].evidence.source_hash
    child_hash = child.dossier.evidence_bindings[0].evidence.source_hash

    assert transition.added_evidence_source_hashes == (child_hash,)
    assert transition.removed_evidence_source_hashes == (parent_hash,)


def test_transition_reports_added_removed_and_changed_findings():
    work_archive, order = _work_order_archive()
    dimension = order.requirements[0].dimension
    parent = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        dimensions=(dimension,),
        finding_id="finding:stable-id",
        finding_statement="initial statement",
    )
    changed = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        dimensions=(dimension,),
        finding_id="finding:stable-id",
        finding_statement="revised statement",
        parent=parent,
    )

    first_transition = evaluate_research_progression(
        (parent, changed)
    ).transitions[0]

    assert first_transition.added_finding_ids == ()
    assert first_transition.removed_finding_ids == ()
    assert first_transition.changed_finding_ids == ("finding:stable-id",)

    removed = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-22T20:00:00+00:00",
        dimensions=(dimension,),
        parent=changed,
    )
    removal = evaluate_research_progression(
        (changed, removed)
    ).transitions[0]

    assert removal.added_finding_ids == ()
    assert removal.removed_finding_ids == ("finding:stable-id",)
    assert removal.changed_finding_ids == ()


def test_transition_describes_new_contradiction_without_rejecting_it():
    work_archive, order = _work_order_archive()
    dimension = order.requirements[0].dimension
    parent = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        dimensions=(dimension,),
        direction=ResearchEvidenceDirection.SUPPORTING,
    )
    child = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        dimensions=(dimension,),
        direction=ResearchEvidenceDirection.CONTRADICTING,
        parent=parent,
    )

    transition = evaluate_research_progression(
        (parent, child)
    ).transitions[0]

    assert not transition.contradictions_before
    assert transition.contradictions_after


def test_transition_describes_new_unresolved_state_without_rejecting_it():
    work_archive, order = _work_order_archive()
    dimension = order.requirements[0].dimension
    parent = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        dimensions=(dimension,),
    )
    child = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        dimensions=(dimension,),
        unresolved=True,
        parent=parent,
    )

    transition = evaluate_research_progression(
        (parent, child)
    ).transitions[0]

    assert not transition.unresolved_before
    assert transition.unresolved_after


def test_snapshot_burden_exposes_requirement_and_source_deficits_as_vector():
    work_archive, order = _work_order_archive(
        minimum_independent_sources=2
    )
    record = _theme_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        dimensions=(order.requirements[0].dimension,),
    )

    report = evaluate_research_progression((record,))
    snapshot = report.snapshots[0]
    burden = snapshot.burden

    assert burden.archive_record_hash == record.archive_record_hash
    assert burden.unsatisfied_requirements == tuple(
        order.requirements[1:]
    )
    assert burden.unresolved_finding_ids == ()
    assert not burden.contradictions_present
    assert burden.independent_source_deficit == 1
    assert burden.company_burdens == ()


def test_company_burden_preserves_deficit_linkage_state_and_cautions():
    record = _company_burden_record()

    report = evaluate_research_progression((record,))
    burden = report.snapshots[0].burden

    assert len(burden.company_burdens) == 1
    company = burden.company_burdens[0]
    assert company.ticker == "AAA"
    assert company.independent_source_deficit == 1
    assert company.linkage_status is CompanyLinkageStatus.NOT_PROVIDED
    assert company.cautions == ("independent source minimum not met",)


def test_progression_has_no_scalar_progress_or_burden_score():
    _, _, root = _root()
    report = evaluate_research_progression((root,))

    report_fields = {item.name for item in fields(report)}
    snapshot_fields = {item.name for item in fields(report.snapshots[0])}

    assert "progress_score" not in report_fields
    assert "score" not in report_fields
    assert "burden" in snapshot_fields

    burden_fields = {
        item.name for item in fields(report.snapshots[0].burden)
    }
    assert "score" not in burden_fields
    assert "burden_score" not in burden_fields
