import pytest

from decision_lab.research_budget import (
    ResearchAllocation,
    ResearchBudgetAllocator,
    ResearchBudgetConfig,
    ResearchTier,
)
from decision_lab.scanner import (
    ScannerConfig,
    SupportDirection,
    ThemeScanObservation,
    ThemeScanResult,
    rank_themes,
)
from decision_lab.themes import (
    ThemeCalibrationState,
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemeLifecycleState,
)


def _registry():
    return {
        "DataCenter_Infra": ThemeDefinition(
            theme_id="DataCenter_Infra",
            display_name="Data Center Infrastructure",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            version="1",
        ),
        "Genomics_Bio": ThemeDefinition(
            theme_id="Genomics_Bio",
            display_name="Genomics and Biotechnology",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            version="1",
        ),
    }


def _scan(
    theme_id,
    *,
    as_of="2026-09-19",
    priority=0.80,
    confidence=0.70,
    novelty=0.50,
    independent_support=1,
    contradictions=0,
    forced=False,
    severity=0,
):
    return ThemeScanResult(
        theme_id=theme_id,
        as_of=as_of,
        discovery_score=0.8,
        structural_score=0.8,
        persistence_score=0.8,
        breadth_score=0.8,
        relative_strength_score=0.8,
        novelty_score=novelty,
        evidence_confidence=confidence,
        independent_support_count=independent_support,
        independent_contradiction_count=contradictions,
        lifecycle_recommendation="no_change",
        research_priority=priority,
        forced_review=forced,
        forced_review_severity=severity,
        forced_review_reasons=("forced",) if forced else (),
        reasons=(),
        evidence_refs=(f"scan:{theme_id}",),
        config_hash="scanner-config",
        registry_version="1",
        prior_result_refs=(),
    )


def test_model_only_strength_remains_scan_only():
    result = ResearchBudgetAllocator().allocate(
        [_scan("DataCenter_Infra", independent_support=0)],
        _registry(),
        (),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.tier is ResearchTier.SCAN_ONLY
    assert "independent corroboration missing" in result.allocation_reasons


def test_strengthening_theme_with_independent_support_can_enter_theme_research():
    scan = _scan("DataCenter_Infra", priority=0.55, novelty=0.20)

    result = ResearchBudgetAllocator().allocate(
        [scan],
        _registry(),
        (),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.tier is ResearchTier.THEME_RESEARCH


def test_high_priority_novel_strengthening_theme_can_enter_full_research():
    result = ResearchBudgetAllocator().allocate(
        [_scan("DataCenter_Infra", priority=0.80, novelty=0.50)],
        _registry(),
        (),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.tier is ResearchTier.FULL_DECISION_RESEARCH


def test_unknown_theme_never_enters_package_dependent_research():
    result = ResearchBudgetAllocator().allocate(
        [_scan("Unknown_Theme", priority=1.0, novelty=1.0, forced=True, severity=3)],
        _registry(),
        (),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.tier is ResearchTier.SCAN_ONLY
    assert "theme not registered" in result.allocation_reasons


def test_forced_review_preempts_lower_priority_ordinary_full_slot():
    config = ResearchBudgetConfig(theme_research_slots=2, full_decision_slots=1)
    forced = _scan("Genomics_Bio", priority=0.40, novelty=0.10, forced=True, severity=3)
    ordinary = _scan("DataCenter_Infra", priority=0.95, novelty=0.90)

    results = ResearchBudgetAllocator().allocate(
        [ordinary, forced],
        _registry(),
        (),
        config,
        cycle_as_of="2026-09-19",
    )
    by_theme = {item.theme_id: item for item in results}

    assert by_theme["Genomics_Bio"].tier is ResearchTier.FULL_DECISION_RESEARCH
    assert by_theme["DataCenter_Infra"].tier is ResearchTier.THEME_RESEARCH


def test_forced_review_over_capacity_respects_caps_and_deterministic_order():
    registry = {
        name: ThemeDefinition(
            theme_id=name,
            display_name=name,
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            version="1",
        )
        for name in ("A", "B", "C")
    }
    scans = [
        _scan("C", forced=True, severity=2, priority=0.9),
        _scan("B", forced=True, severity=3, priority=0.7),
        _scan("A", forced=True, severity=3, priority=0.8),
    ]
    config = ResearchBudgetConfig(theme_research_slots=2, full_decision_slots=2)

    results = ResearchBudgetAllocator().allocate(
        scans,
        registry,
        (),
        config,
        cycle_as_of="2026-09-19",
    )
    full = [
        item.theme_id
        for item in results
        if item.tier is ResearchTier.FULL_DECISION_RESEARCH
    ]

    assert full == ["A", "B"]


def test_full_research_consumes_exactly_one_theme_slot():
    registry = {
        name: ThemeDefinition(
            theme_id=name,
            display_name=name,
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            version="1",
        )
        for name in ("A", "B", "C")
    }
    scans = [_scan("A"), _scan("B"), _scan("C")]
    config = ResearchBudgetConfig(theme_research_slots=2, full_decision_slots=2)

    results = ResearchBudgetAllocator().allocate(
        scans,
        registry,
        (),
        config,
        cycle_as_of="2026-09-19",
    )
    expensive = [item for item in results if item.tier is not ResearchTier.SCAN_ONLY]

    assert len(expensive) == 2


def test_uncalibrated_themekey_does_not_block_research_or_become_satisfied():
    scan = _scan("Genomics_Bio", priority=0.90, novelty=0.80)

    allocation = ResearchBudgetAllocator().allocate(
        [scan],
        _registry(),
        (),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    policy = ThemeKeyPolicy(
        calibration_state=ThemeCalibrationState.UNCALIBRATED,
        minimum_flow=0.50,
    )
    theme_key = policy.evaluate(
        flow=1.0,
        structure=1.0,
        valid_sessions=100,
        permission="probe",
    )

    assert allocation.tier is ResearchTier.FULL_DECISION_RESEARCH
    assert not theme_key.satisfied


def _prior_allocation(
    theme_id,
    as_of,
    *,
    tier=ResearchTier.FULL_DECISION_RESEARCH,
    novelty=0.05,
    priority=0.80,
):
    return ResearchAllocation(
        theme_id=theme_id,
        as_of=as_of,
        tier=tier,
        scan_priority=priority,
        effective_priority=priority,
        scan_novelty_score=novelty,
        forced_review=False,
        allocation_reasons=("prior",),
        source_scan_result_hash=f"hash:{theme_id}:{as_of}",
    )


def test_prior_expensive_low_novelty_allocations_reduce_effective_priority():
    priors = [
        _prior_allocation("DataCenter_Infra", "2026-09-16"),
        _prior_allocation("DataCenter_Infra", "2026-09-17"),
        _prior_allocation("DataCenter_Infra", "2026-09-18"),
    ]
    current = _scan("DataCenter_Infra", priority=0.80, novelty=0.10)

    allocation = ResearchBudgetAllocator().allocate(
        [current],
        _registry(),
        priors,
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert allocation.scan_priority == 0.80
    assert allocation.effective_priority == 0.50


def test_prior_scan_only_low_novelty_does_not_create_decay():
    priors = [
        _prior_allocation(
            "DataCenter_Infra",
            "2026-09-18",
            tier=ResearchTier.SCAN_ONLY,
            novelty=0.01,
        )
    ]
    current = _scan("DataCenter_Infra", priority=0.80, novelty=0.10)

    allocation = ResearchBudgetAllocator().allocate(
        [current],
        _registry(),
        priors,
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert allocation.effective_priority == 0.80


def test_forced_review_bypasses_prior_expensive_no_change_decay():
    priors = [
        _prior_allocation("Genomics_Bio", "2026-09-16"),
        _prior_allocation("Genomics_Bio", "2026-09-17"),
        _prior_allocation("Genomics_Bio", "2026-09-18"),
    ]
    forced = _scan(
        "Genomics_Bio",
        priority=0.80,
        novelty=0.10,
        forced=True,
        severity=3,
    )

    allocation = ResearchBudgetAllocator().allocate(
        [forced],
        _registry(),
        priors,
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert allocation.tier is ResearchTier.FULL_DECISION_RESEARCH
    assert allocation.effective_priority == allocation.scan_priority == 0.80


def test_same_or_future_prior_allocation_is_rejected_from_decay_history():
    prior = _prior_allocation("DataCenter_Infra", "2026-09-19")

    with pytest.raises(ValueError, match="prior research allocation must be strictly earlier"):
        ResearchBudgetAllocator().allocate(
            [_scan("DataCenter_Infra")],
            _registry(),
            [prior],
            ResearchBudgetConfig(),
            cycle_as_of="2026-09-19",
        )


def test_stale_scanner_confidence_can_block_ordinary_promotion():
    stale_observation = ThemeScanObservation(
        theme_id="DataCenter_Infra",
        as_of="2026-09-09",
        source_type="market_data",
        source_ref="market:stale",
        discovery_signal=0.9,
        structure_signal=0.9,
        persistence_signal=0.9,
        breadth_signal=0.9,
        relative_strength_signal=0.9,
        novelty_signal=0.9,
        support_direction=SupportDirection.SUPPORTING,
        evidence_refs=("market:stale",),
        is_independent=True,
        observed_or_inferred="observed",
    )
    stale_scan = rank_themes(
        [stale_observation],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    allocation = ResearchBudgetAllocator().allocate(
        [stale_scan],
        _registry(),
        (),
        ResearchBudgetConfig(confidence_floor=0.55),
        cycle_as_of="2026-09-19",
    )[0]

    assert stale_scan.evidence_confidence < 0.55
    assert allocation.tier is ResearchTier.SCAN_ONLY
    assert "evidence confidence below floor" in allocation.allocation_reasons


def test_allocator_tie_break_is_deterministic():
    registry = {
        name: ThemeDefinition(
            theme_id=name,
            display_name=name,
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            version="1",
        )
        for name in ("A", "B")
    }
    scans = [_scan("B"), _scan("A")]

    first = ResearchBudgetAllocator().allocate(
        scans,
        registry,
        (),
        ResearchBudgetConfig(theme_research_slots=1, full_decision_slots=1),
        cycle_as_of="2026-09-19",
    )
    second = ResearchBudgetAllocator().allocate(
        list(reversed(scans)),
        registry,
        (),
        ResearchBudgetConfig(theme_research_slots=1, full_decision_slots=1),
        cycle_as_of="2026-09-19",
    )

    assert first == second
    assert first[0].theme_id == "A"


def test_date_only_cycle_accepts_same_day_timestamped_scan():
    result = ResearchBudgetAllocator().allocate(
        [_scan("DataCenter_Infra", as_of="2026-09-19T16:00:00+00:00")],
        _registry(),
        (),
        ResearchBudgetConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.tier is ResearchTier.FULL_DECISION_RESEARCH


def test_negative_research_slots_are_rejected():
    with pytest.raises(ValueError, match="research slot counts must be non-negative"):
        ResearchBudgetAllocator().allocate(
            [_scan("DataCenter_Infra")],
            _registry(),
            (),
            ResearchBudgetConfig(theme_research_slots=-1),
            cycle_as_of="2026-09-19",
        )
