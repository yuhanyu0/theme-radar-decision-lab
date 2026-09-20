from dataclasses import replace

import pytest

from decision_lab.ledger import canonical_hash
from decision_lab.evidence import EvidenceRecord
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
    ResearchEvidenceDirection,
    ResearchEvidenceInput,
    ResearchFinding,
    ResearchFindingKind,
    ResearchWorkOrderPolicy,
    _freeze_evidence_inputs,
    _normalize_findings,
    _parse_utc,
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
