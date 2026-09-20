from dataclasses import asdict, replace
from pathlib import Path

import pytest

from decision_lab.evidence import EvidenceRecord
from decision_lab.hierarchical import HierarchicalLinkageResult
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
from decision_lab.replay_cohort import RoutingIntent
from decision_lab.research_budget import ResearchBudgetConfig, ResearchTier
from decision_lab.research_execution import (
    CompanyLinkageStatus,
    CompanyLinkageSubmission,
    CompanyResearchSubmission,
    ResearchAuthorization,
    ResearchDossierStatus,
    ResearchEvidenceDirection,
    ResearchEvidenceInput,
    ResearchExecutionClosure,
    ResearchFinding,
    ResearchFindingKind,
    ResearchMode,
    ResearchRequirementScope,
    ResearchWorkOrderPolicy,
    _freeze_evidence_inputs,
    _linkage_status,
    _normalize_company_submissions,
    _normalize_findings,
    _normalize_linkage_submissions,
    _parse_utc,
    build_research_dossier,
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
    load_theme_package,
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


def test_unregistered_forced_review_cannot_be_company_deep_dive():
    record = _unregistered_forced_archive()

    with pytest.raises(ValueError):
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


def test_company_policy_dimension_must_exist_on_selected_adapter():
    record, package = _registered_archive()
    policy = replace(
        ResearchWorkOrderPolicy(),
        industrials_company_dimensions=("not_a_real_dimension",),
    )

    with pytest.raises(
        ValueError,
        match="company requirement dimension is unsupported by adapter",
    ):
        build_research_work_order(
            record,
            "WorkTheme",
            ResearchMode.COMPANY_DEEP_DIVE,
            theme_package=package,
            target_tickers=("AAA",),
            policy=policy,
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


def test_ticker_specific_evidence_cannot_bind_to_another_valid_target():
    record, package = _registered_archive()
    order = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA", "BBB"),
    )
    evidence = _evidence(
        evidence_id="bbb",
        source_ref="sec:bbb",
        ticker="BBB",
        payload={"growth": 0.2},
    )

    with pytest.raises(
        ValueError,
        match="ticker-specific evidence does not match binding target",
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


def test_conflicting_source_metadata_is_rejected():
    record, package = _registered_archive()
    order = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
    )
    first = _evidence(
        evidence_id="a",
        source_ref="same-source",
        ticker="AAA",
        payload={"growth": 0.2},
        source_type="sec_filing",
    )
    second = _evidence(
        evidence_id="b",
        source_ref="same-source",
        ticker="AAA",
        payload={"margin": 0.3},
        source_type="company_ir",
    )

    with pytest.raises(
        ValueError,
        match="conflicting research source metadata",
    ):
        _freeze_evidence_inputs(
            (
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
            order=order,
            evidence_as_of=_parse_utc("2026-09-20"),
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


def test_company_submission_timestamp_before_source_cycle_is_rejected():
    order = _company_order()
    evidence = _evidence(
        evidence_id="aaa",
        source_ref="sec:aaa",
        ticker="AAA",
        payload={"revenue_growth": 0.2},
    )
    _, originals = _one_company_binding(order, evidence, ("growth",))

    with pytest.raises(
        ValueError,
        match="company research as_of is outside execution window",
    ):
        _normalize_company_submissions(
            (
                CompanyResearchSubmission(
                    "AAA",
                    "2026-09-18",
                    "industrials_infrastructure",
                    {"revenue_growth": 0.2},
                    (evidence.source_hash,),
                ),
            ),
            order=order,
            evidence=originals,
            evidence_as_of=_parse_utc("2026-09-20"),
        )


def test_non_finite_linkage_is_rejected():
    order = _company_order()
    bad = replace(_usable_linkage(), beta=float("nan"))

    with pytest.raises(ValueError, match="must be finite"):
        _normalize_linkage_submissions(
            (
                CompanyLinkageSubmission(
                    ticker="AAA",
                    linkage=bad,
                ),
            ),
            order=order,
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


def test_dossier_input_order_and_timezone_spelling_are_semantically_irrelevant():
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


ROOT = Path(__file__).resolve().parents[1]


def _archive_for_real_package(package):
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
                        version="real-package-test",
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
                    market_source_ref=f"fixture:{theme}:market",
                ),
            ),
            external_observations=(
                _strong_observation(theme),
            ),
            prior_scan_results=(),
            prior_allocations=(),
            scanner_config=ScannerConfig(),
            budget_config=ResearchBudgetConfig(),
        )
    )
    return build_replay_archive_record(result)


def _first_effective_ticker(package):
    candidates = package.universe.active_candidates(
        as_of="2026-09-19"
    )
    assert candidates
    return min(
        candidate.ticker.upper()
        for candidate in candidates
    )


def test_real_theme_packages_generate_domain_specific_company_requirements():
    dc_package = load_theme_package(
        ROOT / "config/themes/datacenter_infra.yaml"
    )
    bio_package = load_theme_package(
        ROOT / "config/themes/genomics_bio.yaml"
    )
    dc_record = _archive_for_real_package(dc_package)
    bio_record = _archive_for_real_package(bio_package)

    dc_order = build_research_work_order(
        dc_record,
        "DataCenter_Infra",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=dc_package,
        target_tickers=(
            _first_effective_ticker(dc_package),
        ),
    )
    bio_order = build_research_work_order(
        bio_record,
        "Genomics_Bio",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=bio_package,
        target_tickers=(
            _first_effective_ticker(bio_package),
        ),
    )

    assert dc_order.evidence_adapter == "industrials_infrastructure"
    assert bio_order.evidence_adapter == "biotech_clinical"
    assert (
        dc_order.source_routing_intent
        is RoutingIntent.ORDINARY_FULL_RESEARCH
    )
    assert (
        bio_order.source_routing_intent
        is RoutingIntent.ORDINARY_FULL_RESEARCH
    )

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



def test_dossier_evidence_as_of_cannot_precede_source_cycle():
    record = _unregistered_forced_archive()
    order = build_research_work_order(
        record,
        "UnknownRisk",
        ResearchMode.THEME_REASSESSMENT,
    )

    with pytest.raises(
        ValueError,
        match="evidence_as_of precedes source cycle",
    ):
        build_research_dossier(
            order,
            evidence_as_of="2026-09-18",
            closure=ResearchExecutionClosure.OPEN,
        )


def test_rehashed_semantically_invalid_work_order_is_rejected():
    record, package = _registered_archive()
    order = build_research_work_order(
        record,
        "WorkTheme",
        ResearchMode.COMPANY_DEEP_DIVE,
        theme_package=package,
        target_tickers=("AAA",),
    )
    tampered = replace(
        order,
        authorization=ResearchAuthorization.UNREGISTERED_FORCED_REVIEW,
        work_order_hash="0" * 64,
    )
    payload = asdict(tampered)
    payload.pop("work_order_hash")
    tampered = replace(
        tampered,
        work_order_hash=canonical_hash(payload),
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
