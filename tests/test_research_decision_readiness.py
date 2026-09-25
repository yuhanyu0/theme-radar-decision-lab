from dataclasses import fields, replace

import pytest

from decision_lab.evidence import EvidenceRecord
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
from decision_lab.research_decision_readiness import (
    ResearchDecisionReadinessGate,
    ResearchDecisionReadinessStatus,
    assess_research_decision_readiness,
)
from decision_lab.research_execution import (
    CompanyLinkageSubmission,
    ResearchDossierStatus,
    ResearchFinding,
    ResearchFindingKind,
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


def _package(theme="ReadinessTheme"):
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
                        version="readiness-test",
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
                    market_source_ref="fixture:readiness-market",
                ),
            ),
            external_observations=(
                ThemeScanObservation(
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
    return EvidenceRecord(
        evidence_id=f"ev:{suffix}",
        observed_at=evidence_as_of,
        retrieved_at=evidence_as_of,
        market_asof=None,
        ticker=None,
        theme="ReadinessTheme",
        source_type="official_macro",
        source_ref=f"official:{suffix}",
        fact_type="readiness_fact",
        payload={"state": suffix},
        is_observed_fact=True,
    ).with_hash()


def _archive_record(
    work_archive,
    order,
    *,
    evidence_as_of,
    complete,
    closure,
    parent=None,
    direction=ResearchEvidenceDirection.SUPPORTING,
    unresolved=False,
):
    evidence = _evidence(
        evidence_as_of=evidence_as_of,
        suffix=evidence_as_of,
    )
    dimensions = (
        tuple(item.dimension for item in order.requirements)
        if complete
        else (order.requirements[0].dimension,)
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
                dimensions=dimensions,
                target_ticker=None,
            ),
        ),
        findings=(
            (
                ResearchFinding(
                    finding_id=f"unresolved:{evidence_as_of}",
                    kind=ResearchFindingKind.UNRESOLVED,
                    direction=None,
                    dimension=order.requirements[0].dimension,
                    target_ticker=None,
                    statement="research question remains unresolved",
                    evidence_source_hashes=(),
                ),
            )
            if unresolved
            else ()
        ),
    )
    return build_research_dossier_archive_record(
        work_archive,
        dossier,
        prior_dossier_archive=parent,
    )


def _ready_root():
    work_archive, order = _work_order_archive()
    root = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
    )
    assert root.dossier.status is ResearchDossierStatus.COMPLETE
    return work_archive, order, root


def test_readiness_rejects_absent_candidate():
    _, _, root = _ready_root()

    with pytest.raises(ValueError, match="candidate is not present"):
        assess_research_decision_readiness(
            (root,),
            "0" * 64,
        )


def test_non_leaf_candidate_is_not_ready():
    work_archive, order, root = _ready_root()
    child = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
    )

    assessment = assess_research_decision_readiness(
        (child, root),
        root.archive_record_hash,
    )

    assert assessment.status is ResearchDecisionReadinessStatus.NOT_READY
    gate = {
        item.gate: item.passed
        for item in assessment.gate_results
    }
    assert not gate[ResearchDecisionReadinessGate.CANDIDATE_IS_LEAF]
    assert assessment.candidate_sufficient is False


def test_complete_but_open_candidate_is_not_ready():
    work_archive, order = _work_order_archive()
    candidate = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.OPEN,
    )

    assessment = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )

    assert candidate.dossier.status is ResearchDossierStatus.COMPLETE
    assert assessment.status is ResearchDecisionReadinessStatus.NOT_READY
    gates = {
        item.gate: item.passed
        for item in assessment.gate_results
    }
    assert gates[ResearchDecisionReadinessGate.DOSSIER_COMPLETE]
    assert not gates[ResearchDecisionReadinessGate.EXECUTION_CLOSED]


def test_closed_but_incomplete_candidate_is_not_ready():
    work_archive, order = _work_order_archive()
    candidate = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=False,
        closure=ResearchExecutionClosure.CLOSED,
    )

    assessment = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )

    assert (
        candidate.dossier.status
        is ResearchDossierStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    )
    assert assessment.status is ResearchDecisionReadinessStatus.NOT_READY
    gates = {
        item.gate: item.passed
        for item in assessment.gate_results
    }
    assert not gates[ResearchDecisionReadinessGate.DOSSIER_COMPLETE]
    assert gates[ResearchDecisionReadinessGate.EXECUTION_CLOSED]


def test_unique_complete_closed_root_is_ready_for_decision_analysis():
    _, _, candidate = _ready_root()

    assessment = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )

    assert assessment.status is ResearchDecisionReadinessStatus.READY
    assert assessment.candidate_sufficient
    assert assessment.selection_determinate
    assert assessment.competing_leaf_archive_record_hashes == ()
    assert all(item.passed for item in assessment.gate_results)
    assert (
        "not trading permission"
        in " ".join(assessment.limitations)
    )


def test_gate_order_is_fixed_and_auditable():
    _, _, candidate = _ready_root()

    assessment = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )

    assert tuple(
        item.gate for item in assessment.gate_results
    ) == (
        ResearchDecisionReadinessGate.CANDIDATE_IS_LEAF,
        ResearchDecisionReadinessGate.DOSSIER_COMPLETE,
        ResearchDecisionReadinessGate.EXECUTION_CLOSED,
        ResearchDecisionReadinessGate.NO_UNSATISFIED_REQUIREMENTS,
        ResearchDecisionReadinessGate.NO_UNRESOLVED_FINDINGS,
        ResearchDecisionReadinessGate.GLOBAL_SOURCE_MINIMUM_MET,
        ResearchDecisionReadinessGate.COMPANY_SOURCE_MINIMUMS_MET,
        ResearchDecisionReadinessGate.LINEAGE_COMPLETE,
        ResearchDecisionReadinessGate.UNIQUE_OBSERVED_LEAF,
    )


def test_readiness_has_no_scalar_score_field():
    _, _, candidate = _ready_root()
    assessment = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )

    names = {item.name for item in fields(assessment)}

    assert "score" not in names
    assert "readiness_score" not in names
    assert "confidence_score" not in names
    assert "completion_percentage" not in names


def test_input_permutation_preserves_assessment_and_hash():
    work_archive, order = _work_order_archive()
    root = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=False,
        closure=ResearchExecutionClosure.OPEN,
    )
    candidate = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
    )

    first = assess_research_decision_readiness(
        (root, candidate),
        candidate.archive_record_hash,
    )
    second = assess_research_decision_readiness(
        (candidate, root),
        candidate.archive_record_hash,
    )

    assert first == second
    assert (
        first.readiness_assessment_hash
        == second.readiness_assessment_hash
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
                        version="readiness-company-test",
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
                    market_source_ref="fixture:readiness-company-market",
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
        require_usable_linkage_for_company=False,
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
    archive = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    return archive, order


def test_unresolved_finding_blocks_readiness():
    work_archive, order = _work_order_archive()
    candidate = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        unresolved=True,
    )

    assert candidate.dossier.status is ResearchDossierStatus.COMPLETE
    assessment = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )
    gates = {item.gate: item.passed for item in assessment.gate_results}

    assert assessment.status is ResearchDecisionReadinessStatus.NOT_READY
    assert not gates[
        ResearchDecisionReadinessGate.NO_UNRESOLVED_FINDINGS
    ]


def test_global_source_deficit_blocks_readiness():
    work_archive, order = _work_order_archive(
        minimum_independent_sources=2
    )
    candidate = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
    )

    assessment = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )
    gates = {item.gate: item.passed for item in assessment.gate_results}

    assert candidate.dossier.independent_source_count == 1
    assert assessment.status is ResearchDecisionReadinessStatus.NOT_READY
    assert not gates[
        ResearchDecisionReadinessGate.GLOBAL_SOURCE_MINIMUM_MET
    ]


def test_company_source_deficit_blocks_readiness():
    work_archive, order = _company_work_order_archive()
    dossier = build_research_dossier(
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        closure=ResearchExecutionClosure.CLOSED,
    )
    candidate = build_research_dossier_archive_record(
        work_archive,
        dossier,
    )

    assessment = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )
    gates = {item.gate: item.passed for item in assessment.gate_results}

    assert len(candidate.dossier.company_assessments) == 1
    assert (
        candidate.dossier.company_assessments[0].independent_source_count
        == 0
    )
    assert assessment.status is ResearchDecisionReadinessStatus.NOT_READY
    assert not gates[
        ResearchDecisionReadinessGate.COMPANY_SOURCE_MINIMUMS_MET
    ]


def test_contradiction_alone_does_not_block_readiness():
    work_archive, order = _work_order_archive()
    candidate = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        direction=ResearchEvidenceDirection.CONTRADICTING,
    )

    assert candidate.dossier.contradictions_present
    assessment = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )

    assert assessment.status is ResearchDecisionReadinessStatus.READY
    assert assessment.contradictions_present
    assert assessment.candidate_sufficient
    assert assessment.selection_determinate


def test_locally_sufficient_orphan_is_indeterminate():
    work_archive, order = _work_order_archive()
    parent = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=False,
        closure=ResearchExecutionClosure.OPEN,
    )
    orphan = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        parent=parent,
    )

    assessment = assess_research_decision_readiness(
        (orphan,),
        orphan.archive_record_hash,
    )
    gates = {item.gate: item.passed for item in assessment.gate_results}

    assert assessment.candidate_sufficient
    assert assessment.status is ResearchDecisionReadinessStatus.INDETERMINATE
    assert not assessment.selection_determinate
    assert not gates[ResearchDecisionReadinessGate.LINEAGE_COMPLETE]


def test_locally_sufficient_candidate_with_competing_leaf_is_indeterminate():
    work_archive, order = _work_order_archive()
    root = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=False,
        closure=ResearchExecutionClosure.OPEN,
    )
    candidate = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
    )
    sibling = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-22T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
    )

    assessment = assess_research_decision_readiness(
        (sibling, root, candidate),
        candidate.archive_record_hash,
    )
    gates = {item.gate: item.passed for item in assessment.gate_results}

    assert assessment.candidate_sufficient
    assert assessment.status is ResearchDecisionReadinessStatus.INDETERMINATE
    assert not assessment.selection_determinate
    assert not gates[
        ResearchDecisionReadinessGate.UNIQUE_OBSERVED_LEAF
    ]
    assert assessment.competing_leaf_archive_record_hashes == (
        sibling.archive_record_hash,
    )


def test_local_insufficiency_precedes_branch_indeterminacy():
    work_archive, order = _work_order_archive()
    root = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=False,
        closure=ResearchExecutionClosure.OPEN,
    )
    candidate = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.OPEN,
        parent=root,
    )
    sibling = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-22T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
    )

    assessment = assess_research_decision_readiness(
        (candidate, sibling, root),
        candidate.archive_record_hash,
    )

    assert not assessment.candidate_sufficient
    assert assessment.status is ResearchDecisionReadinessStatus.NOT_READY
    assert assessment.competing_leaf_archive_record_hashes == (
        sibling.archive_record_hash,
    )


def test_competing_leaves_are_sorted_deterministically():
    work_archive, order = _work_order_archive()
    root = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=False,
        closure=ResearchExecutionClosure.OPEN,
    )
    candidate = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
    )
    sibling_a = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-22T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
    )
    sibling_b = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-23T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
    )

    assessment = assess_research_decision_readiness(
        (sibling_b, candidate, root, sibling_a),
        candidate.archive_record_hash,
    )

    assert assessment.competing_leaf_archive_record_hashes == tuple(
        sorted(
            (
                sibling_a.archive_record_hash,
                sibling_b.archive_record_hash,
            )
        )
    )


def test_historical_reopen_and_completion_loss_are_visible_not_blocking():
    work_archive, order = _work_order_archive()
    root = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
    )
    regressed = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        complete=False,
        closure=ResearchExecutionClosure.OPEN,
        parent=root,
    )
    candidate = _archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-22T20:00:00+00:00",
        complete=True,
        closure=ResearchExecutionClosure.CLOSED,
        parent=regressed,
    )

    assessment = assess_research_decision_readiness(
        (candidate, root, regressed),
        candidate.archive_record_hash,
    )

    assert assessment.status is ResearchDecisionReadinessStatus.READY
    assert assessment.execution_reopen_count == 1
    assert assessment.completion_loss_count == 1
    assert assessment.candidate_sufficient
    assert assessment.selection_determinate


def test_company_cautions_are_preserved_and_sorted_without_hidden_gate():
    work_archive, order = _company_work_order_archive()
    pending_linkage = LinkageResult(
        ticker="AAA",
        control_name="theme-minus-AAA",
        window=63,
        correlation=None,
        beta=None,
        r2=None,
        residual_mean=None,
        residual_vol=None,
        beta_stability=None,
        decoupling_score=None,
        circularity_warning=False,
        observations=10,
    )
    dossier = build_research_dossier(
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        closure=ResearchExecutionClosure.CLOSED,
        linkage_submissions=(
            CompanyLinkageSubmission(
                ticker="AAA",
                linkage=pending_linkage,
            ),
        ),
    )
    candidate = build_research_dossier_archive_record(
        work_archive,
        dossier,
    )

    assessment = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )

    assert tuple(
        (item.ticker, item.caution)
        for item in assessment.company_cautions
    ) == (
        ("AAA", "independent source minimum not met"),
        ("AAA", "linkage coverage pending"),
    )


def test_readiness_limitations_keep_downstream_boundary_explicit():
    _, _, candidate = _ready_root()

    assessment = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )
    joined = " ".join(assessment.limitations)

    assert "not trading permission" in joined
    assert "Tape" in joined
    assert "playbook" in joined
    assert "no canonical fork or root is selected" in joined
