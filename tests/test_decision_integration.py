from dataclasses import fields, replace

from decision_lab.decision import compile_decision
from decision_lab.decision_integration import (
    DecisionRoutingInputs,
    ResearchDecisionAdmissionStatus,
    evaluate_research_decision_integration,
)
from decision_lab.evidence import EvidenceRecord
from decision_lab.linkage import LinkageResult
from decision_lab.market_observation import (
    MarketBar,
    MarketObservationConfig,
    MarketObservationMode,
    MarketObservationSpec,
)
from decision_lab.playbooks import route_playbooks
from decision_lab.replay import ReplayCycleInput, ThemeReplayInput, run_replay_cycle
from decision_lab.replay_archive import build_replay_archive_record
from decision_lab.research_budget import ResearchBudgetConfig
from decision_lab.research_execution import (
    CompanyLinkageSubmission,
    CompanyResearchSubmission,
    ResearchDossierStatus,
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
from decision_lab.tape import TapeAssessment
from decision_lab.themes import (
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemeLifecycleState,
    ThemePackage,
)
from decision_lab.universe import Candidate, ThemeLayer, ThemeUniverse


def _tape(*, state="clean_retest", stage="B3"):
    return TapeAssessment(
        state=state,
        stage=stage,
        support=90.0,
        reclaim=100.0,
        pivot=105.0,
        invalidation=88.0,
        higher_low=True,
        new_low_recently=False,
        volume_confirmation=True,
        volatility_contraction=False,
        relative_strength_positive=True,
        reasons=("fixture tape",),
    )


def _routing_inputs(**overrides):
    base = dict(
        theme_key=True,
        fundamentals_intact=True,
        true_catalyst=False,
        breakout_confirmed=False,
        squeeze_confirmed=False,
        stable_regime=False,
        overheated_without_upgrade=False,
        pair_divergence=False,
        structural_repricing=False,
        world_confidence="high",
    )
    base.update(overrides)
    return DecisionRoutingInputs(**base)


def _direct_route(tape, inputs):
    return route_playbooks(
        theme_key=inputs.theme_key,
        tape_state=tape.state,
        tape_stage=tape.stage,
        fundamentals_intact=inputs.fundamentals_intact,
        true_catalyst=inputs.true_catalyst,
        breakout_confirmed=inputs.breakout_confirmed,
        squeeze_confirmed=inputs.squeeze_confirmed,
        stable_regime=inputs.stable_regime,
        overheated_without_upgrade=inputs.overheated_without_upgrade,
        pair_divergence=inputs.pair_divergence,
        structural_repricing=inputs.structural_repricing,
        world_confidence=inputs.world_confidence,
    )


def _theme_package(theme="IntegrationTheme"):
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


def _theme_ready_record():
    package = _theme_package()
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
                    evidence_refs=(f"fixture:{theme}:contradiction",),
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
        theme,
        ResearchMode.THEME_REASSESSMENT,
        theme_package=package,
        policy=policy,
    )
    work_archive = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    evidence_as_of = "2026-09-20T20:00:00+00:00"
    evidence = EvidenceRecord(
        evidence_id="ev:integration",
        observed_at=evidence_as_of,
        retrieved_at=evidence_as_of,
        market_asof=None,
        ticker=None,
        theme=theme,
        source_type="official_macro",
        source_ref="official:integration",
        fact_type="integration_fact",
        payload={"state": "ready"},
        is_observed_fact=True,
    ).with_hash()
    dossier = build_research_dossier(
        order,
        evidence_as_of=evidence_as_of,
        closure=ResearchExecutionClosure.CLOSED,
        evidence_inputs=(
            ResearchEvidenceInput(
                evidence=evidence,
                independent=True,
                direction=ResearchEvidenceDirection.SUPPORTING,
                dimensions=tuple(
                    requirement.dimension
                    for requirement in order.requirements
                ),
                target_ticker=None,
            ),
        ),
    )
    record = build_research_dossier_archive_record(
        work_archive,
        dossier,
    )
    return theme, record


def test_compile_decision_accepts_explicit_created_at():
    tape = _tape()
    routing = _direct_route(tape, _routing_inputs())
    created_at = "2026-09-25T12:00:00+00:00"

    decision = compile_decision(
        decision_id="decision-explicit-time",
        created_at=created_at,
        market_asof="2026-09-25T11:59:00+00:00",
        theme="IntegrationTheme",
        ticker="AAA",
        theme_state="active",
        theme_key=True,
        company_state="researched",
        tape=tape,
        routing=routing,
        strongest_reason_not_to_trade="fixture caution",
        model_version="integration-test",
        config_payload={"version": 1},
    )

    assert decision["created_at"] == created_at


def test_compile_decision_default_created_at_path_remains_supported():
    tape = _tape()
    routing = _direct_route(tape, _routing_inputs())

    decision = compile_decision(
        decision_id="decision-default-time",
        market_asof="2026-09-25T11:59:00+00:00",
        theme="IntegrationTheme",
        ticker="AAA",
        theme_state="active",
        theme_key=True,
        company_state="researched",
        tape=tape,
        routing=routing,
        strongest_reason_not_to_trade="fixture caution",
        model_version="integration-test",
        config_payload={"version": 1},
    )

    assert decision["created_at"]
    assert len(decision["decision_payload_hash"]) == 64


def test_routing_inputs_do_not_duplicate_tape_state_or_stage():
    names = {item.name for item in fields(DecisionRoutingInputs)}

    assert "tape_state" not in names
    assert "tape_stage" not in names


def test_integration_routes_from_supplied_tape():
    theme, record = _theme_ready_record()
    tape = _tape(state="clean_retest", stage="B3")
    routing_inputs = _routing_inputs()

    integration = evaluate_research_decision_integration(
        (record,),
        record.archive_record_hash,
        requested_theme=theme,
        requested_ticker="AAA",
        tape=tape,
        routing_inputs=routing_inputs,
    )
    expected = _direct_route(tape, routing_inputs)

    assert integration.tape == tape
    assert integration.routing == expected
    assert integration.market_action == expected.action


def test_integration_hashes_are_deterministic():
    theme, record = _theme_ready_record()
    tape = _tape()
    routing_inputs = _routing_inputs()

    first = evaluate_research_decision_integration(
        (record,),
        record.archive_record_hash,
        requested_theme=theme,
        requested_ticker="AAA",
        tape=tape,
        routing_inputs=routing_inputs,
    )
    second = evaluate_research_decision_integration(
        (record,),
        record.archive_record_hash,
        requested_theme=theme,
        requested_ticker="AAA",
        tape=tape,
        routing_inputs=routing_inputs,
    )

    assert first == second
    assert len(first.tape_hash) == 64
    assert len(first.routing_inputs_hash) == 64
    assert len(first.routing_hash) == 64
    assert len(first.integration_hash) == 64


def _company_ready_record():
    package = _theme_package()
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
                        version="integration-company-test",
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
                    market_source_ref="fixture:integration-company-market",
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
        minimum_independent_sources_per_company=1,
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
    work_archive = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    evidence_as_of = "2026-09-20T20:00:00+00:00"
    evidence = EvidenceRecord(
        evidence_id="ev:integration-company",
        observed_at=evidence_as_of,
        retrieved_at=evidence_as_of,
        market_asof=None,
        ticker="AAA",
        theme=theme,
        source_type="sec_filing",
        source_ref="sec:AAA:integration",
        fact_type="integration_company_fact",
        payload={"revenue_growth": 0.2},
        is_observed_fact=True,
    ).with_hash()
    dossier = build_research_dossier(
        order,
        evidence_as_of=evidence_as_of,
        closure=ResearchExecutionClosure.CLOSED,
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
                as_of=evidence_as_of,
                adapter_name="industrials_infrastructure",
                raw_facts={"revenue_growth": 0.2},
                evidence_source_hashes=(evidence.source_hash,),
            ),
        ),
        linkage_submissions=(
            CompanyLinkageSubmission(
                ticker="AAA",
                linkage=LinkageResult(
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
                ),
            ),
        ),
    )
    assert dossier.status is ResearchDossierStatus.COMPLETE
    record = build_research_dossier_archive_record(
        work_archive,
        dossier,
    )
    return theme, record


def _theme_not_ready_record():
    theme, ready = _theme_ready_record()
    order = ready.work_order_archive.work_order
    dossier = build_research_dossier(
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        closure=ResearchExecutionClosure.CLOSED,
    )
    record = build_research_dossier_archive_record(
        ready.work_order_archive,
        dossier,
    )
    return theme, record


def _theme_orphan_ready_record():
    theme, parent = _theme_ready_record()
    order = parent.work_order_archive.work_order
    evidence_as_of = "2026-09-21T20:00:00+00:00"
    evidence = EvidenceRecord(
        evidence_id="ev:integration-orphan",
        observed_at=evidence_as_of,
        retrieved_at=evidence_as_of,
        market_asof=None,
        ticker=None,
        theme=theme,
        source_type="official_macro",
        source_ref="official:integration-orphan",
        fact_type="integration_orphan_fact",
        payload={"state": "ready"},
        is_observed_fact=True,
    ).with_hash()
    dossier = build_research_dossier(
        order,
        evidence_as_of=evidence_as_of,
        closure=ResearchExecutionClosure.CLOSED,
        evidence_inputs=(
            ResearchEvidenceInput(
                evidence=evidence,
                independent=True,
                direction=ResearchEvidenceDirection.SUPPORTING,
                dimensions=tuple(
                    requirement.dimension
                    for requirement in order.requirements
                ),
                target_ticker=None,
            ),
        ),
    )
    child = build_research_dossier_archive_record(
        parent.work_order_archive,
        dossier,
        prior_dossier_archive=parent,
    )
    return theme, child


def test_not_ready_research_is_not_admitted():
    theme, record = _theme_not_ready_record()

    integration = evaluate_research_decision_integration(
        (record,),
        record.archive_record_hash,
        requested_theme=theme,
        requested_ticker="AAA",
        tape=_tape(),
        routing_inputs=_routing_inputs(),
    )

    assert (
        integration.admission_status
        is ResearchDecisionAdmissionStatus.RESEARCH_NOT_READY
    )
    assert integration.admitted_action is None
    assert integration.market_action == "BUILD_ON_RETEST"


def test_indeterminate_research_is_not_admitted():
    theme, orphan = _theme_orphan_ready_record()

    integration = evaluate_research_decision_integration(
        (orphan,),
        orphan.archive_record_hash,
        requested_theme=theme,
        requested_ticker="AAA",
        tape=_tape(),
        routing_inputs=_routing_inputs(),
    )

    assert (
        integration.admission_status
        is ResearchDecisionAdmissionStatus.RESEARCH_INDETERMINATE
    )
    assert integration.admitted_action is None


def test_ready_theme_reassessment_is_scope_mismatch_for_ticker_decision():
    theme, record = _theme_ready_record()

    integration = evaluate_research_decision_integration(
        (record,),
        record.archive_record_hash,
        requested_theme=theme,
        requested_ticker="AAA",
        tape=_tape(),
        routing_inputs=_routing_inputs(),
    )

    assert (
        integration.admission_status
        is ResearchDecisionAdmissionStatus.RESEARCH_SCOPE_MISMATCH
    )
    assert integration.scope_mismatch_reasons == (
        "company-level research is required",
    )
    assert integration.admitted_action is None


def test_ready_company_research_requires_exact_theme_and_target_ticker():
    theme, record = _company_ready_record()

    wrong_both = evaluate_research_decision_integration(
        (record,),
        record.archive_record_hash,
        requested_theme="WrongTheme",
        requested_ticker="BBB",
        tape=_tape(),
        routing_inputs=_routing_inputs(),
    )

    assert (
        wrong_both.admission_status
        is ResearchDecisionAdmissionStatus.RESEARCH_SCOPE_MISMATCH
    )
    assert wrong_both.scope_mismatch_reasons == (
        "decision theme does not match research work order",
        "decision ticker is not a frozen research target",
    )
    assert wrong_both.admitted_action is None

    correct = evaluate_research_decision_integration(
        (record,),
        record.archive_record_hash,
        requested_theme=theme,
        requested_ticker="aaa",
        tape=_tape(),
        routing_inputs=_routing_inputs(),
    )

    assert correct.admission_status is ResearchDecisionAdmissionStatus.ADMITTED
    assert correct.scope_mismatch_reasons == ()
    assert correct.requested_ticker == "AAA"
    assert correct.admitted_action == correct.market_action


def test_scope_mismatch_reasons_have_fixed_order():
    theme, record = _theme_ready_record()

    integration = evaluate_research_decision_integration(
        (record,),
        record.archive_record_hash,
        requested_theme="WrongTheme",
        requested_ticker="BBB",
        tape=_tape(),
        routing_inputs=_routing_inputs(),
    )

    assert integration.scope_mismatch_reasons == (
        "company-level research is required",
        "decision theme does not match research work order",
        "decision ticker is not a frozen research target",
    )
