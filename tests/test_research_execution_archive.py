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
from decision_lab.research_budget import ResearchBudgetConfig
from decision_lab.research_execution import (
    ResearchMode,
    ResearchWorkOrderPolicy,
    build_research_work_order,
)
from decision_lab.research_execution_archive import (
    ResearchWorkOrderArchiveRecord,
    build_research_work_order_archive_record,
    research_work_order_archive_path,
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


def _package(theme="ArchiveResearchTheme"):
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


def _source_observation(theme, *, direction=SupportDirection.SUPPORTING):
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
        is_independent=True,
        observed_or_inferred="observed",
    )


def _replay_archive_and_order(
    *,
    direction=SupportDirection.SUPPORTING,
    policy=None,
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
                        version="archive-test",
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
                    market_source_ref="fixture:archive-market",
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
    replay_archive = build_replay_archive_record(result)
    raw_policy = (
        ResearchWorkOrderPolicy()
        if policy is None
        else policy
    )
    work_order_policy = replace(
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
    mode = (
        ResearchMode.COMPANY_DEEP_DIVE
        if direction is SupportDirection.SUPPORTING
        else ResearchMode.THEME_REASSESSMENT
    )
    order = build_research_work_order(
        replay_archive,
        theme,
        mode,
        theme_package=package,
        target_tickers=("AAA",)
        if mode is ResearchMode.COMPANY_DEEP_DIVE
        else (),
        policy=work_order_policy,
    )
    return replay_archive, order, work_order_policy


def test_work_order_archive_builder_freezes_policy_and_replay_lineage():
    replay_archive, order, policy = _replay_archive_and_order()

    first = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    second = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )

    assert isinstance(first, ResearchWorkOrderArchiveRecord)
    assert first == second
    assert first.source_cycle_as_of == replay_archive.cycle_as_of
    assert (
        first.source_replay_archive_record_hash
        == replay_archive.archive_record_hash
    )
    assert first.source_replay_result_hash == replay_archive.replay_result_hash
    assert first.work_order_hash == order.work_order_hash
    assert first.work_order == order
    assert first.work_order_policy == policy
    assert len(first.archive_record_hash) == 64
    assert first.archive_record_hash == first.archive_record_hash.lower()


def test_work_order_archive_rejects_mismatched_policy():
    replay_archive, order, policy = _replay_archive_and_order()
    wrong = replace(
        policy,
        minimum_independent_sources=policy.minimum_independent_sources + 1,
    )

    with pytest.raises(
        ValueError,
        match="research work order policy mismatch",
    ):
        build_research_work_order_archive_record(
            replay_archive,
            order,
            work_order_policy=wrong,
        )


def test_work_order_archive_rejects_rehashed_changed_contradiction_questions():
    replay_archive, order, policy = _replay_archive_and_order(
        direction=SupportDirection.CONTRADICTING
    )
    seed = replace(
        order,
        contradiction_questions=("changed research question",),
        work_order_hash="0" * 64,
    )
    payload = asdict(seed)
    payload.pop("work_order_hash")
    tampered = replace(
        seed,
        work_order_hash=canonical_hash(payload),
    )

    with pytest.raises(
        ValueError,
        match="invalid research work order",
    ):
        build_research_work_order_archive_record(
            replay_archive,
            tampered,
            work_order_policy=policy,
        )


def test_work_order_archive_rejects_rehashed_false_routing_provenance():
    replay_archive, _, policy = _replay_archive_and_order()
    forced_replay, forced_order, _ = _replay_archive_and_order(
        direction=SupportDirection.CONTRADICTING
    )
    tampered = replace(
        forced_order,
        source_archive_record_hash=replay_archive.archive_record_hash,
        source_replay_result_hash=replay_archive.replay_result_hash,
        source_cycle_as_of=replay_archive.cycle_as_of,
        work_order_hash="0" * 64,
    )
    payload = asdict(tampered)
    payload.pop("work_order_hash")
    tampered = replace(
        tampered,
        work_order_hash=canonical_hash(payload),
    )

    assert forced_replay.replay_result_hash != replay_archive.replay_result_hash
    with pytest.raises(
        ValueError,
        match="research work order replay lineage mismatch",
    ):
        build_research_work_order_archive_record(
            replay_archive,
            tampered,
            work_order_policy=policy,
        )


def test_work_order_archive_rejects_invalid_source_replay_archive():
    replay_archive, order, policy = _replay_archive_and_order()
    invalid = replace(
        replay_archive,
        archive_record_hash="0" * 64,
    )

    with pytest.raises(
        ValueError,
        match="invalid source replay archive record",
    ):
        build_research_work_order_archive_record(
            invalid,
            order,
            work_order_policy=policy,
        )


def test_work_order_archive_path_uses_source_cycle_and_work_order_hash(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    root = tmp_path / "recomputed" / "research_execution"

    path = research_work_order_archive_path(record, root)

    assert path == (
        root
        / "work_orders"
        / "2026-09-19"
        / f"{order.work_order_hash}.json"
    )
    assert not root.exists()
