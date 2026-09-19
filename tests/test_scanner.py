from copy import deepcopy

import pytest

from decision_lab.scanner import (
    ScannerConfig,
    SupportDirection,
    ThemeScanObservation,
    rank_themes,
)
from decision_lab.themes import ThemeDefinition, ThemeLifecycleState


def _registry():
    return {
        "DataCenter_Infra": ThemeDefinition(
            theme_id="DataCenter_Infra",
            display_name="Data Center Infrastructure",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            effective_from="2026-09-01",
            version="1",
        ),
        "Genomics_Bio": ThemeDefinition(
            theme_id="Genomics_Bio",
            display_name="Genomics and Biotechnology",
            lifecycle_state=ThemeLifecycleState.STRENGTHENING,
            effective_from="2026-09-18",
            version="1",
        ),
    }


def _obs(
    *,
    theme_id="DataCenter_Infra",
    as_of="2026-09-19T15:00:00+00:00",
    source_type="market_data",
    source_ref="market:theme-breadth",
    independent=True,
    support=SupportDirection.SUPPORTING,
    discovery=0.8,
    structure=0.7,
    persistence=0.7,
    breadth=0.7,
    relative_strength=0.7,
    novelty=0.5,
):
    return ThemeScanObservation(
        theme_id=theme_id,
        as_of=as_of,
        source_type=source_type,
        source_ref=source_ref,
        discovery_signal=discovery,
        structure_signal=structure,
        persistence_signal=persistence,
        breadth_signal=breadth,
        relative_strength_signal=relative_strength,
        novelty_signal=novelty,
        support_direction=support,
        evidence_refs=(source_ref,),
        is_independent=independent,
        observed_or_inferred="observed",
    )


def test_future_dated_observation_is_rejected():
    with pytest.raises(ValueError, match="future-dated observation"):
        rank_themes(
            [_obs(as_of="2026-09-20T00:00:00+00:00")],
            _registry(),
            (),
            ScannerConfig(),
            cycle_as_of="2026-09-19T23:59:59+00:00",
        )


def test_radar_observation_cannot_claim_independent_status():
    bad = _obs(
        source_type="radar_model_output",
        source_ref="radar:run-1",
        independent=True,
    )
    with pytest.raises(ValueError, match="radar_model_output cannot be independent"):
        rank_themes(
            [bad],
            _registry(),
            (),
            ScannerConfig(),
            cycle_as_of="2026-09-19T23:59:59+00:00",
        )


def test_duplicate_independent_source_ref_counts_once():
    observations = [
        _obs(source_ref="market:breadth", breadth=0.8),
        _obs(source_ref="market:breadth", breadth=0.9, novelty=0.6),
    ]

    result = rank_themes(
        observations,
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )[0]

    assert result.independent_support_count == 1


def test_duplicate_source_ref_does_not_reweight_component_aggregation():
    baseline = rank_themes(
        [
            _obs(source_ref="market:a", breadth=0.2),
            _obs(source_ref="market:b", breadth=0.8),
        ],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]
    duplicated = rank_themes(
        [
            _obs(source_ref="market:a", breadth=0.2),
            _obs(source_ref="market:a", breadth=0.2),
            _obs(source_ref="market:b", breadth=0.8),
        ],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert duplicated.breadth_score == baseline.breadth_score


def test_naive_and_offset_timestamps_normalize_to_same_cycle():
    observations = [
        _obs(as_of="2026-09-19T15:00:00", source_ref="market:naive"),
        _obs(as_of="2026-09-19T11:00:00-04:00", source_ref="market:offset"),
    ]

    result = rank_themes(
        observations,
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T15:00:00+00:00",
    )[0]

    assert result.independent_support_count == 2


def test_missing_components_remain_none_and_priority_is_finite_zero():
    observation = ThemeScanObservation(
        theme_id="DataCenter_Infra",
        as_of="2026-09-19",
        source_type="market_data",
        source_ref="market:empty",
        support_direction=SupportDirection.NEUTRAL,
        evidence_refs=("market:empty",),
        is_independent=True,
        observed_or_inferred="observed",
    )

    result = rank_themes(
        [observation],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert result.discovery_score is None
    assert result.structural_score is None
    assert result.breadth_score is None
    assert result.research_priority == 0.0


def test_model_and_independent_sources_are_aggregated_but_counted_separately():
    observations = [
        _obs(
            source_type="radar_model_output",
            source_ref="radar:run-1",
            independent=False,
            discovery=1.0,
            structure=0.9,
        ),
        _obs(
            source_type="market_data",
            source_ref="market:breadth",
            independent=True,
            discovery=0.6,
            structure=0.6,
        ),
    ]

    result = rank_themes(
        observations,
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )[0]

    assert result.discovery_score is not None
    assert result.structural_score is not None
    assert result.independent_support_count == 1
    assert result.independent_contradiction_count == 0
    assert 0.0 <= result.evidence_confidence <= 1.0
    assert 0.0 <= result.research_priority <= 1.0


def test_independent_support_raises_priority_over_model_only_evidence():
    radar = _obs(
        source_type="radar_model_output",
        source_ref="radar:run-1",
        independent=False,
        discovery=0.9,
        structure=0.8,
        persistence=0.8,
        breadth=0.8,
        relative_strength=0.8,
        novelty=0.5,
    )
    independent = _obs(
        source_type="market_data",
        source_ref="market:breadth",
        independent=True,
        discovery=0.9,
        structure=0.8,
        persistence=0.8,
        breadth=0.8,
        relative_strength=0.8,
        novelty=0.5,
    )

    model_only = rank_themes(
        [radar],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )[0]
    corroborated = rank_themes(
        [radar, independent],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )[0]

    assert model_only.independent_support_count == 0
    assert corroborated.independent_support_count == 1
    assert corroborated.evidence_confidence > model_only.evidence_confidence
    assert corroborated.research_priority > model_only.research_priority


def test_stale_independent_evidence_lowers_confidence_and_priority():
    fresh = rank_themes(
        [_obs(as_of="2026-09-19", source_ref="market:fresh")],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]
    stale = rank_themes(
        [_obs(as_of="2026-09-09", source_ref="market:stale")],
        _registry(),
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19",
    )[0]

    assert stale.evidence_confidence < fresh.evidence_confidence
    assert stale.research_priority < fresh.research_priority


def test_scanner_does_not_mutate_registry_state():
    registry = _registry()
    before = deepcopy(registry)

    rank_themes(
        [_obs()],
        registry,
        (),
        ScannerConfig(),
        cycle_as_of="2026-09-19T23:59:59+00:00",
    )

    assert registry == before
