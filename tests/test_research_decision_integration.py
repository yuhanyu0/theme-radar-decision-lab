from dataclasses import asdict, replace

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
from decision_lab.research_decision_integration import (
    ResearchDecisionAdmissionStatus,
    ResearchDecisionRoutingInputs,
    compile_research_gated_decision,
    evaluate_research_decision_admission,
)
from decision_lab.playbooks import route_playbooks
from decision_lab.research_decision_readiness import (
    ResearchDecisionReadinessStatus,
    assess_research_decision_readiness,
)
from decision_lab.research_execution import (
    CompanyLinkageSubmission,
    CompanyResearchSubmission,
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
from decision_lab.tape import TapeAssessment
from decision_lab.universe import Candidate, ThemeLayer, ThemeUniverse


def _package(theme="IntegrationTheme"):
    universe = ThemeUniverse(
        theme=theme,
        version="u1",
        generated_at="2026-09-19T00:00:00Z",
    )
    universe.add_layer(ThemeLayer("primary"))
    for ticker in ("AAA", "BBB"):
        universe.add_candidate(
            Candidate(
                ticker=ticker,
                theme=theme,
                layer="primary",
                effective_from="2026-01-01",
                provenance=(f"fixture:{ticker}",),
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


def _source_observation(
    theme,
    *,
    direction=SupportDirection.SUPPORTING,
):
    return ThemeScanObservation(
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
        support_direction=direction,
        evidence_refs=(f"fixture:{theme}",),
        is_independent=True,
        observed_or_inferred="observed",
    )


def _replay_archive_and_package(
    *,
    direction=SupportDirection.SUPPORTING,
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
                        version="integration-test",
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
                    market_source_ref="fixture:integration-market",
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
    return build_replay_archive_record(result), package


def _company_work_order_archive(*, targets=("AAA",)):
    replay_archive, package = _replay_archive_and_package()
    raw_policy = replace(
        ResearchWorkOrderPolicy(),
        industrials_company_dimensions=("growth",),
        minimum_independent_sources=1,
        minimum_independent_sources_per_company=1,
        require_usable_linkage_for_company=True,
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
        package.definition.theme_id,
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=targets,
        policy=policy,
    )
    archive = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    return archive, order


def _theme_work_order_archive():
    replay_archive, package = _replay_archive_and_package(
        direction=SupportDirection.CONTRADICTING,
    )
    raw_policy = replace(
        ResearchWorkOrderPolicy(),
        minimum_independent_sources=1,
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
        package.definition.theme_id,
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


def _evidence(*, evidence_as_of, ticker=None, suffix="a"):
    return EvidenceRecord(
        evidence_id=f"ev:{suffix}",
        observed_at=evidence_as_of,
        retrieved_at=evidence_as_of,
        market_asof=None,
        ticker=ticker,
        theme="IntegrationTheme",
        source_type="sec_filing" if ticker else "official_macro",
        source_ref=f"source:{suffix}",
        fact_type="integration_fact",
        payload={"revenue_growth": 0.2} if ticker else {"state": suffix},
        is_observed_fact=True,
    ).with_hash()


def _usable_linkage(ticker):
    return LinkageResult(
        ticker=ticker,
        control_name=f"theme-minus-{ticker}",
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


def _company_archive_record(
    work_archive,
    order,
    *,
    evidence_as_of,
    closure,
    parent=None,
    complete=True,
):
    evidence_inputs = []
    company_submissions = []
    linkage_submissions = []

    if complete:
        for index, target in enumerate(order.targets):
            evidence = _evidence(
                evidence_as_of=evidence_as_of,
                ticker=target.ticker,
                suffix=f"{target.ticker}:{index}:{evidence_as_of}",
            )
            evidence_inputs.append(
                ResearchEvidenceInput(
                    evidence=evidence,
                    independent=True,
                    direction=ResearchEvidenceDirection.SUPPORTING,
                    dimensions=("growth",),
                    target_ticker=target.ticker,
                )
            )
            company_submissions.append(
                CompanyResearchSubmission(
                    ticker=target.ticker,
                    as_of=evidence_as_of,
                    adapter_name="industrials_infrastructure",
                    raw_facts={"revenue_growth": 0.2},
                    evidence_source_hashes=(evidence.source_hash,),
                )
            )
            linkage_submissions.append(
                CompanyLinkageSubmission(
                    ticker=target.ticker,
                    linkage=_usable_linkage(target.ticker),
                )
            )

    dossier = build_research_dossier(
        order,
        evidence_as_of=evidence_as_of,
        closure=closure,
        evidence_inputs=tuple(evidence_inputs),
        company_submissions=tuple(company_submissions),
        linkage_submissions=tuple(linkage_submissions),
    )
    return build_research_dossier_archive_record(
        work_archive,
        dossier,
        prior_dossier_archive=parent,
    )


def _theme_ready_record():
    work_archive, order = _theme_work_order_archive()
    evidence = _evidence(
        evidence_as_of="2026-09-20T20:00:00+00:00",
        ticker=None,
        suffix="theme-ready",
    )
    dimensions = tuple(item.dimension for item in order.requirements)
    dossier = build_research_dossier(
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        closure=ResearchExecutionClosure.CLOSED,
        evidence_inputs=(
            ResearchEvidenceInput(
                evidence=evidence,
                independent=True,
                direction=ResearchEvidenceDirection.SUPPORTING,
                dimensions=dimensions,
                target_ticker=None,
            ),
        ),
    )
    record = build_research_dossier_archive_record(
        work_archive,
        dossier,
    )
    readiness = assess_research_decision_readiness(
        (record,),
        record.archive_record_hash,
    )
    assert readiness.status is ResearchDecisionReadinessStatus.READY
    return record, readiness


def _company_ready_root(*, targets=("AAA",)):
    work_archive, order = _company_work_order_archive(targets=targets)
    record = _company_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        closure=ResearchExecutionClosure.CLOSED,
        complete=True,
    )
    readiness = assess_research_decision_readiness(
        (record,),
        record.archive_record_hash,
    )
    assert readiness.status is ResearchDecisionReadinessStatus.READY
    return work_archive, order, record, readiness


def test_admission_rejects_readiness_that_does_not_match_records():
    _, _, record, readiness = _company_ready_root()
    altered = replace(
        readiness,
        contradictions_present=not readiness.contradictions_present,
    )

    with pytest.raises(ValueError, match="does not match supplied records"):
        evaluate_research_decision_admission(
            (record,),
            altered,
            "AAA",
        )


def test_admission_rejects_stale_ready_after_competing_leaf_appears():
    work_archive, order = _company_work_order_archive()
    root = _company_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        closure=ResearchExecutionClosure.OPEN,
        complete=False,
    )
    candidate = _company_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
        complete=True,
    )
    old_ready = assess_research_decision_readiness(
        (root, candidate),
        candidate.archive_record_hash,
    )
    assert old_ready.status is ResearchDecisionReadinessStatus.READY

    sibling = _company_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-22T20:00:00+00:00",
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
        complete=True,
    )

    with pytest.raises(ValueError, match="does not match supplied records"):
        evaluate_research_decision_admission(
            (candidate, sibling, root),
            old_ready,
            "AAA",
        )


def test_theme_reassessment_ready_cannot_authorize_ticker_decision():
    record, readiness = _theme_ready_record()

    with pytest.raises(ValueError, match="company deep dive"):
        evaluate_research_decision_admission(
            (record,),
            readiness,
            "AAA",
        )


def test_admission_rejects_non_target_ticker():
    _, _, record, readiness = _company_ready_root(targets=("AAA",))

    with pytest.raises(ValueError, match="ticker is not a work order target"):
        evaluate_research_decision_admission(
            (record,),
            readiness,
            "BBB",
        )


def test_ready_company_target_is_admitted_and_ticker_is_normalized():
    _, order, record, readiness = _company_ready_root(targets=("AAA",))

    admission = evaluate_research_decision_admission(
        (record,),
        readiness,
        "aaa",
    )

    assert admission.status is ResearchDecisionAdmissionStatus.ADMITTED
    assert admission.theme_id == order.theme_id
    assert admission.ticker == "AAA"
    assert admission.work_order_hash == order.work_order_hash
    assert (
        admission.candidate_archive_record_hash
        == record.archive_record_hash
    )
    assert (
        admission.readiness_assessment_hash
        == readiness.readiness_assessment_hash
    )
    assert len(admission.admission_hash) == 64


def test_not_ready_company_state_is_blocked_not_ready():
    work_archive, order = _company_work_order_archive()
    candidate = _company_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        closure=ResearchExecutionClosure.OPEN,
        complete=True,
    )
    readiness = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )
    assert readiness.status is ResearchDecisionReadinessStatus.NOT_READY

    admission = evaluate_research_decision_admission(
        (candidate,),
        readiness,
        "AAA",
    )

    assert (
        admission.status
        is ResearchDecisionAdmissionStatus.BLOCKED_NOT_READY
    )


def test_indeterminate_company_state_is_blocked_indeterminate():
    work_archive, order = _company_work_order_archive()
    root = _company_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        closure=ResearchExecutionClosure.OPEN,
        complete=False,
    )
    candidate = _company_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
        complete=True,
    )
    sibling = _company_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-22T20:00:00+00:00",
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
        complete=True,
    )
    records = (root, candidate, sibling)
    readiness = assess_research_decision_readiness(
        records,
        candidate.archive_record_hash,
    )
    assert readiness.status is ResearchDecisionReadinessStatus.INDETERMINATE

    admission = evaluate_research_decision_admission(
        records,
        readiness,
        "AAA",
    )

    assert (
        admission.status
        is ResearchDecisionAdmissionStatus.BLOCKED_INDETERMINATE
    )


def test_admission_is_independent_of_record_input_order():
    work_archive, order = _company_work_order_archive()
    root = _company_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        closure=ResearchExecutionClosure.OPEN,
        complete=False,
    )
    candidate = _company_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        closure=ResearchExecutionClosure.CLOSED,
        parent=root,
        complete=True,
    )
    readiness = assess_research_decision_readiness(
        (root, candidate),
        candidate.archive_record_hash,
    )

    first = evaluate_research_decision_admission(
        (root, candidate),
        readiness,
        "AAA",
    )
    second = evaluate_research_decision_admission(
        (candidate, root),
        readiness,
        "AAA",
    )

    assert first == second
    assert first.admission_hash == second.admission_hash


def test_multi_target_work_order_never_auto_selects_target():
    _, _, record, readiness = _company_ready_root(
        targets=("AAA", "BBB")
    )

    aaa = evaluate_research_decision_admission(
        (record,),
        readiness,
        "AAA",
    )
    bbb = evaluate_research_decision_admission(
        (record,),
        readiness,
        "BBB",
    )

    assert aaa.ticker == "AAA"
    assert bbb.ticker == "BBB"
    assert aaa.admission_hash != bbb.admission_hash



def _tape(*, state="reclaim", stage="B2"):
    return TapeAssessment(
        state=state,
        stage=stage,
        support=90.0,
        reclaim=100.0,
        pivot=105.0,
        invalidation=85.0,
        higher_low=stage in {"B2", "B3"},
        new_low_recently=state == "falling_knife",
        volume_confirmation=False,
        volatility_contraction=False,
        relative_strength_positive=True,
        reasons=("fixture tape",),
    )


def _compile_kwargs(*, tape, theme_key=True, routing_inputs=None):
    _, _, record, readiness = _company_ready_root()
    return {
        "records": (record,),
        "readiness": readiness,
        "ticker": "AAA",
        "tape": tape,
        "theme_key": theme_key,
        "routing_inputs": (
            ResearchDecisionRoutingInputs(world_confidence="high")
            if routing_inputs is None
            else routing_inputs
        ),
        "decision_id": "decision-integration-001",
        "market_asof": "2026-09-24T20:00:00+00:00",
        "theme_state": "confirmed",
        "company_state": "researched",
        "strongest_reason_not_to_trade": "execution risk remains",
        "model_version": "integration-v0.1",
        "config_payload": {"fixture": True},
    }


def test_blocked_research_admission_cannot_compile_decision():
    work_archive, order = _company_work_order_archive()
    candidate = _company_archive_record(
        work_archive,
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        closure=ResearchExecutionClosure.OPEN,
        complete=True,
    )
    readiness = assess_research_decision_readiness(
        (candidate,),
        candidate.archive_record_hash,
    )
    assert readiness.status is ResearchDecisionReadinessStatus.NOT_READY

    with pytest.raises(ValueError, match="research admission is not ADMITTED"):
        compile_research_gated_decision(
            records=(candidate,),
            readiness=readiness,
            ticker="AAA",
            tape=_tape(),
            theme_key=True,
            routing_inputs=ResearchDecisionRoutingInputs(
                world_confidence="high"
            ),
            decision_id="decision-blocked-001",
            market_asof="2026-09-24T20:00:00+00:00",
            theme_state="confirmed",
            company_state="researched",
            strongest_reason_not_to_trade="research is open",
            model_version="integration-v0.1",
            config_payload={"fixture": True},
        )


def test_routing_is_derived_from_exact_tape_and_inputs():
    tape = _tape(state="reclaim", stage="B2")
    routing_inputs = ResearchDecisionRoutingInputs(
        fundamentals_intact=True,
        world_confidence="high",
    )
    result = compile_research_gated_decision(
        **_compile_kwargs(
            tape=tape,
            theme_key=True,
            routing_inputs=routing_inputs,
        )
    )
    direct = route_playbooks(
        theme_key=True,
        tape_state=tape.state,
        tape_stage=tape.stage,
        fundamentals_intact=True,
        world_confidence="high",
    )

    assert result.routing == direct
    assert result.decision["playbooks"]["scores"] == dict(
        direct.normalized_scores
    )
    assert result.decision["playbooks"]["raw_scores"] == dict(
        direct.raw_scores
    )
    assert result.decision["playbooks"]["selected"] == direct.selected_playbook
    assert result.decision["action"] == direct.action


def test_theme_key_is_shared_by_router_and_decision():
    result = compile_research_gated_decision(
        **_compile_kwargs(
            tape=_tape(state="reclaim", stage="B2"),
            theme_key=False,
        )
    )

    assert result.decision["theme_key"] is False
    assert result.routing.action == "WATCH_ONLY"
    assert result.decision["action"] == "WATCH_ONLY"


def test_world_confidence_is_shared_by_router_and_decision():
    routing_inputs = ResearchDecisionRoutingInputs(
        fundamentals_intact=True,
        world_confidence="low",
    )
    result = compile_research_gated_decision(
        **_compile_kwargs(
            tape=_tape(state="reclaim", stage="B2"),
            theme_key=True,
            routing_inputs=routing_inputs,
        )
    )
    direct = route_playbooks(
        theme_key=True,
        tape_state="reclaim",
        tape_stage="B2",
        fundamentals_intact=True,
        world_confidence="low",
    )

    assert result.routing == direct
    assert result.decision["world_confidence"] == "low"


def test_ready_research_does_not_override_falling_knife_block():
    result = compile_research_gated_decision(
        **_compile_kwargs(
            tape=_tape(state="falling_knife", stage="B0"),
            theme_key=True,
        )
    )

    assert result.routing.selected_playbook == "NoTrade"
    assert result.routing.action == "BLOCKED"
    assert result.decision["action"] == "BLOCKED"


def test_ready_research_preserves_clean_retest_build_action():
    routing_inputs = ResearchDecisionRoutingInputs(
        fundamentals_intact=True,
        world_confidence="high",
    )
    result = compile_research_gated_decision(
        **_compile_kwargs(
            tape=_tape(state="clean_retest", stage="B3"),
            theme_key=True,
            routing_inputs=routing_inputs,
        )
    )
    direct = route_playbooks(
        theme_key=True,
        tape_state="clean_retest",
        tape_stage="B3",
        fundamentals_intact=True,
        world_confidence="high",
    )

    assert direct.action == "BUILD_ON_RETEST"
    assert result.routing == direct
    assert result.decision["action"] == direct.action


def test_decision_theme_and_ticker_come_from_admission_binding():
    kwargs = _compile_kwargs(
        tape=_tape(state="reclaim", stage="B2"),
        theme_key=True,
    )
    result = compile_research_gated_decision(**kwargs)

    assert result.decision["theme"] == result.admission.theme_id
    assert result.decision["ticker"] == result.admission.ticker
    assert result.decision["theme"] == "IntegrationTheme"
    assert result.decision["ticker"] == "AAA"


def test_decision_contains_exact_supplied_tape_snapshot():
    tape = _tape(state="clean_retest", stage="B3")
    result = compile_research_gated_decision(
        **_compile_kwargs(tape=tape, theme_key=True)
    )

    assert result.tape == tape
    assert result.decision["tape"]["state"] == tape.state
    assert result.decision["tape"]["stage"] == tape.stage
    assert result.decision["tape"]["support"] == tape.support
    assert result.decision["tape"]["reasons"] == tape.reasons



def test_compilation_preserves_exact_research_provenance():
    kwargs = _compile_kwargs(
        tape=_tape(state="clean_retest", stage="B3"),
        theme_key=True,
    )
    result = compile_research_gated_decision(**kwargs)

    assert (
        result.readiness_assessment_hash
        == kwargs["readiness"].readiness_assessment_hash
    )
    assert (
        result.candidate_archive_record_hash
        == kwargs["readiness"].candidate_archive_record_hash
    )
    assert result.work_order_hash == result.admission.work_order_hash
    assert result.theme_id == result.admission.theme_id
    assert result.ticker == result.admission.ticker


def test_compilation_preserves_exact_child_components_and_reason():
    tape = _tape(state="reclaim", stage="B2")
    kwargs = _compile_kwargs(tape=tape, theme_key=True)
    result = compile_research_gated_decision(**kwargs)

    assert result.admission.status is ResearchDecisionAdmissionStatus.ADMITTED
    assert result.tape == tape
    assert result.decision["action"] == result.routing.action
    assert (
        result.decision["strongest_reason_not_to_trade"]
        == kwargs["strongest_reason_not_to_trade"]
    )
    assert result.decision["theme"] == result.theme_id
    assert result.decision["ticker"] == result.ticker


def test_child_decision_payload_hash_still_uses_existing_compiler_semantics():
    result = compile_research_gated_decision(
        **_compile_kwargs(
            tape=_tape(state="reclaim", stage="B2"),
            theme_key=True,
        )
    )
    payload = dict(result.decision)
    decision_hash = payload.pop("decision_payload_hash")

    assert decision_hash == canonical_hash(payload)


def test_compilation_hash_covers_exact_integration_payload():
    result = compile_research_gated_decision(
        **_compile_kwargs(
            tape=_tape(state="clean_retest", stage="B3"),
            theme_key=True,
            routing_inputs=ResearchDecisionRoutingInputs(
                fundamentals_intact=True,
                world_confidence="high",
            ),
        )
    )
    payload = asdict(result)
    actual_hash = payload.pop("compilation_hash")

    assert actual_hash == result.compilation_hash
    assert actual_hash == canonical_hash(payload)
    assert len(actual_hash) == 64


def test_compilation_is_an_event_and_keeps_existing_created_at():
    result = compile_research_gated_decision(
        **_compile_kwargs(
            tape=_tape(state="reclaim", stage="B2"),
            theme_key=True,
        )
    )

    assert result.decision["created_at"]
    assert result.decision["decision_payload_hash"]
    assert "created_at" in result.decision


def test_compilation_has_no_ledger_write_side_effect(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = compile_research_gated_decision(
        **_compile_kwargs(
            tape=_tape(state="reclaim", stage="B2"),
            theme_key=True,
        )
    )

    assert result.decision["decision_payload_hash"]
    assert tuple(tmp_path.iterdir()) == ()
