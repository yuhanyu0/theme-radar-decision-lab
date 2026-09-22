from dataclasses import asdict, replace
import json

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
    ResearchDossierArchiveRecord,
    ResearchWorkOrderArchiveRecord,
    build_research_dossier_archive_record,
    build_research_work_order_archive_record,
    read_research_dossier_archive,
    read_research_work_order_archive,
    research_dossier_archive_path,
    research_work_order_archive_path,
    verify_research_dossier_archive,
    verify_research_work_order_archive,
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



def _hashed_evidence(
    *,
    evidence_id,
    source_ref,
    payload,
    theme="ArchiveResearchTheme",
    ticker=None,
    source_type="official_macro",
):
    raw = EvidenceRecord(
        evidence_id=evidence_id,
        observed_at="2026-09-20T12:00:00+00:00",
        retrieved_at="2026-09-20T13:00:00+00:00",
        market_asof=None,
        ticker=ticker,
        theme=theme,
        source_type=source_type,
        source_ref=source_ref,
        fact_type="archive_research_fact",
        payload=dict(payload),
        is_observed_fact=True,
    )
    return raw.with_hash()


def _theme_work_order_archive():
    replay_archive, order, policy = _replay_archive_and_order(
        direction=SupportDirection.CONTRADICTING,
        policy=replace(
            ResearchWorkOrderPolicy(),
            minimum_independent_sources=1,
        ),
    )
    archive = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    return archive, order


def _theme_dossier(
    order,
    *,
    evidence_as_of,
    closure=ResearchExecutionClosure.OPEN,
    include_all_requirements=True,
):
    evidence = _hashed_evidence(
        evidence_id=f"ev:{evidence_as_of}",
        source_ref=f"official:{evidence_as_of}",
        payload={"state": evidence_as_of},
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


def _company_archive_and_dossier(*, hierarchical=False):
    replay_archive, order, policy = _replay_archive_and_order(
        policy=replace(
            ResearchWorkOrderPolicy(),
            industrials_company_dimensions=("growth",),
            minimum_independent_sources=1,
            minimum_independent_sources_per_company=1,
        )
    )
    work_archive = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    evidence = _hashed_evidence(
        evidence_id="ev:AAA",
        source_ref="sec:AAA",
        payload={"revenue_growth": 0.2},
        ticker="AAA",
        source_type="sec_filing",
    )
    linkage = LinkageResult(
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
    hierarchical_linkage = HierarchicalLinkageResult(
        target="AAA",
        status="ok",
        window=63,
        observations=63,
        theme_correlation=0.6,
        theme_beta=0.7,
        r2=0.5,
        incremental_theme_r2=0.2,
        residual_mean=0.0,
        residual_vol=0.02,
        circularity_warning=False,
        missing_controls=(),
        coefficients={"SPY": 0.3, "ArchiveResearchTheme": 0.7},
    )
    linkage_submission = (
        CompanyLinkageSubmission(
            ticker="AAA",
            hierarchical_linkage=hierarchical_linkage,
        )
        if hierarchical
        else CompanyLinkageSubmission(
            ticker="AAA",
            linkage=linkage,
        )
    )
    dossier = build_research_dossier(
        order,
        evidence_as_of="2026-09-20T23:00:00+00:00",
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
                as_of="2026-09-20T20:00:00+00:00",
                adapter_name="industrials_infrastructure",
                raw_facts={"revenue_growth": 0.2},
                evidence_source_hashes=(evidence.source_hash,),
            ),
        ),
        linkage_submissions=(linkage_submission,),
    )
    assert dossier.status is ResearchDossierStatus.COMPLETE
    return work_archive, dossier


def test_dossier_archive_root_and_child_preserve_explicit_lineage():
    work_archive, order = _theme_work_order_archive()
    root_dossier = _theme_dossier(
        order,
        evidence_as_of="2026-09-20T20:00:00+00:00",
        include_all_requirements=False,
    )
    root = build_research_dossier_archive_record(
        work_archive,
        root_dossier,
    )
    child_dossier = _theme_dossier(
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        include_all_requirements=True,
    )
    child = build_research_dossier_archive_record(
        work_archive,
        child_dossier,
        prior_dossier_archive=root,
    )

    assert isinstance(root, ResearchDossierArchiveRecord)
    assert root.prior_dossier_archive_record_hash is None
    assert (
        child.prior_dossier_archive_record_hash
        == root.archive_record_hash
    )
    assert child.work_order_archive == work_archive
    assert child.dossier_hash == child_dossier.dossier_hash


@pytest.mark.parametrize(
    "child_time",
    [
        "2026-09-20T20:00:00+00:00",
        "2026-09-20T16:00:00-04:00",
        "2026-09-20T19:59:59+00:00",
    ],
)
def test_dossier_parent_must_be_strictly_earlier(child_time):
    work_archive, order = _theme_work_order_archive()
    parent = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
        ),
    )
    child_dossier = _theme_dossier(
        order,
        evidence_as_of=child_time,
    )

    with pytest.raises(
        ValueError,
        match="research dossier parent must be strictly earlier",
    ):
        build_research_dossier_archive_record(
            work_archive,
            child_dossier,
            prior_dossier_archive=parent,
        )


def test_dossier_parent_must_match_exact_work_order_archive():
    theme_work_archive, theme_order = _theme_work_order_archive()
    company_work_archive, company_dossier = _company_archive_and_dossier()
    company_parent = build_research_dossier_archive_record(
        company_work_archive,
        company_dossier,
    )
    child_dossier = _theme_dossier(
        theme_order,
        evidence_as_of="2026-09-22T20:00:00+00:00",
    )

    with pytest.raises(
        ValueError,
        match="research dossier parent work order mismatch",
    ):
        build_research_dossier_archive_record(
            theme_work_archive,
            child_dossier,
            prior_dossier_archive=company_parent,
        )


def test_dossier_archive_allows_complete_to_partial_and_forks():
    work_archive, order = _theme_work_order_archive()
    complete = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
            include_all_requirements=True,
        ),
    )
    partial_a = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-21T20:00:00+00:00",
            include_all_requirements=False,
        ),
        prior_dossier_archive=complete,
    )
    partial_b = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-22T20:00:00+00:00",
            include_all_requirements=False,
        ),
        prior_dossier_archive=complete,
    )

    assert complete.dossier.status is ResearchDossierStatus.COMPLETE
    assert partial_a.dossier.status is ResearchDossierStatus.PARTIAL
    assert partial_b.dossier.status is ResearchDossierStatus.PARTIAL
    assert (
        partial_a.prior_dossier_archive_record_hash
        == complete.archive_record_hash
    )
    assert (
        partial_b.prior_dossier_archive_record_hash
        == complete.archive_record_hash
    )


def test_dossier_archive_allows_later_evidence_retraction():
    work_archive, order = _theme_work_order_archive()
    complete = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
            include_all_requirements=True,
        ),
    )
    empty_dossier = build_research_dossier(
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
        closure=ResearchExecutionClosure.OPEN,
    )
    child = build_research_dossier_archive_record(
        work_archive,
        empty_dossier,
        prior_dossier_archive=complete,
    )

    assert complete.dossier.evidence_bindings
    assert child.dossier.evidence_bindings == ()
    assert child.dossier.status is ResearchDossierStatus.NOT_STARTED


def test_same_dossier_with_different_parent_lineage_has_distinct_archive_identity(
    tmp_path,
):
    work_archive, order = _theme_work_order_archive()
    parent_a = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T18:00:00+00:00",
        ),
    )
    parent_b = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T19:00:00+00:00",
        ),
    )
    dossier = _theme_dossier(
        order,
        evidence_as_of="2026-09-21T20:00:00+00:00",
    )
    first = build_research_dossier_archive_record(
        work_archive,
        dossier,
        prior_dossier_archive=parent_a,
    )
    second = build_research_dossier_archive_record(
        work_archive,
        dossier,
        prior_dossier_archive=parent_b,
    )

    assert first.dossier_hash == second.dossier_hash
    assert first.archive_record_hash != second.archive_record_hash
    first_path = research_dossier_archive_path(first, tmp_path)
    second_path = research_dossier_archive_path(second, tmp_path)
    assert first_path != second_path
    assert first_path.name == f"{first.archive_record_hash}.json"
    assert second_path.name == f"{second.archive_record_hash}.json"


def _rehash_dossier(dossier, **changes):
    seed = replace(
        dossier,
        **changes,
        dossier_hash="0" * 64,
    )
    payload = asdict(seed)
    payload.pop("dossier_hash")
    return replace(seed, dossier_hash=canonical_hash(payload))


def test_dossier_archive_rejects_rehashed_false_requirement_partition():
    work_archive, dossier = _company_archive_and_dossier()
    tampered = _rehash_dossier(
        dossier,
        satisfied_requirements=(),
        unsatisfied_requirements=dossier.satisfied_requirements,
    )

    with pytest.raises(ValueError):
        build_research_dossier_archive_record(
            work_archive,
            tampered,
        )


def test_dossier_archive_rejects_rehashed_false_company_assessment():
    work_archive, dossier = _company_archive_and_dossier()
    assessment = dossier.company_assessments[0]
    tampered_assessment = replace(
        assessment,
        independent_source_count=99,
    )
    tampered = _rehash_dossier(
        dossier,
        company_assessments=(tampered_assessment,),
    )

    with pytest.raises(
        ValueError,
        match="inconsistent research company assessment",
    ):
        build_research_dossier_archive_record(
            work_archive,
            tampered,
        )


def test_dossier_archive_rejects_rehashed_noncanonical_company_snapshot():
    work_archive, dossier = _company_archive_and_dossier()
    assessment = dossier.company_assessments[0]
    snapshot = assessment.normalized_evidence
    assert snapshot is not None
    tampered_snapshot = replace(
        snapshot,
        as_of="2026-09-20T16:00:00-04:00",
    )
    tampered_assessment = replace(
        assessment,
        normalized_evidence=tampered_snapshot,
    )
    tampered = _rehash_dossier(
        dossier,
        company_assessments=(tampered_assessment,),
    )

    with pytest.raises(
        ValueError,
        match="inconsistent research company assessment",
    ):
        build_research_dossier_archive_record(
            work_archive,
            tampered,
        )


def test_dossier_archive_rejects_rehashed_hierarchical_source_payload_hash():
    work_archive, dossier = _company_archive_and_dossier(
        hierarchical=True
    )
    assessment = dossier.company_assessments[0]
    snapshot = assessment.hierarchical_linkage
    assert snapshot is not None
    tampered_snapshot = replace(
        snapshot,
        source_payload_hash="1" * 64,
    )
    tampered_assessment = replace(
        assessment,
        hierarchical_linkage=tampered_snapshot,
    )
    tampered = _rehash_dossier(
        dossier,
        company_assessments=(tampered_assessment,),
    )

    with pytest.raises(
        ValueError,
        match="hierarchical linkage source payload hash mismatch",
    ):
        build_research_dossier_archive_record(
            work_archive,
            tampered,
        )



def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            asdict(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def test_work_order_reader_round_trip_preserves_typed_policy_and_order(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    path = research_work_order_archive_path(record, tmp_path)
    _write_json(path, record)

    loaded = read_research_work_order_archive(path)

    assert loaded == record
    assert loaded.work_order_policy == record.work_order_policy
    assert verify_research_work_order_archive(path)


def test_dossier_reader_round_trip_preserves_parent_hash_without_parent_file(
    tmp_path,
):
    work_archive, order = _theme_work_order_archive()
    parent = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
        ),
    )
    child = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-21T20:00:00+00:00",
        ),
        prior_dossier_archive=parent,
    )
    path = research_dossier_archive_path(child, tmp_path)
    _write_json(path, child)

    loaded = read_research_dossier_archive(path)

    assert loaded == child
    assert (
        loaded.prior_dossier_archive_record_hash
        == parent.archive_record_hash
    )
    assert verify_research_dossier_archive(path)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.update(extra_field=True),
        lambda payload: payload.pop("producer"),
        lambda payload: payload.__setitem__(
            "archive_record_hash",
            "0" * 64,
        ),
    ],
)
def test_work_order_reader_rejects_top_level_schema_or_hash_tamper(
    tmp_path,
    mutator,
):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    payload = asdict(record)
    mutator(payload)
    path = research_work_order_archive_path(record, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert not verify_research_work_order_archive(path)
    with pytest.raises((TypeError, ValueError)):
        read_research_work_order_archive(path)


def test_work_order_reader_rejects_wrong_filename(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    path = (
        tmp_path
        / "work_orders"
        / "2026-09-19"
        / f"{'1' * 64}.json"
    )
    _write_json(path, record)

    with pytest.raises(
        ValueError,
        match="research work-order archive filename mismatch",
    ):
        read_research_work_order_archive(path)


def test_work_order_reader_rejects_wrong_cycle_directory(tmp_path):
    replay_archive, order, policy = _replay_archive_and_order()
    record = build_research_work_order_archive_record(
        replay_archive,
        order,
        work_order_policy=policy,
    )
    path = (
        tmp_path
        / "work_orders"
        / "2026-09-18"
        / f"{record.work_order_hash}.json"
    )
    _write_json(path, record)

    with pytest.raises(
        ValueError,
        match="research archive cycle directory mismatch",
    ):
        read_research_work_order_archive(path)


def test_dossier_reader_rejects_wrong_work_order_directory_and_filename(
    tmp_path,
):
    work_archive, order = _theme_work_order_archive()
    record = build_research_dossier_archive_record(
        work_archive,
        _theme_dossier(
            order,
            evidence_as_of="2026-09-20T20:00:00+00:00",
        ),
    )
    wrong_dir = (
        tmp_path
        / "dossiers"
        / "2026-09-19"
        / ("1" * 64)
        / f"{record.archive_record_hash}.json"
    )
    _write_json(wrong_dir, record)
    with pytest.raises(
        ValueError,
        match="research dossier work-order directory mismatch",
    ):
        read_research_dossier_archive(wrong_dir)

    wrong_name = (
        tmp_path
        / "dossiers"
        / "2026-09-19"
        / record.work_order_archive.work_order_hash
        / f"{'2' * 64}.json"
    )
    _write_json(wrong_name, record)
    with pytest.raises(
        ValueError,
        match="research dossier archive filename mismatch",
    ):
        read_research_dossier_archive(wrong_name)


def test_reader_rejects_non_finite_json_constant(tmp_path):
    work_archive, dossier = _company_archive_and_dossier()
    record = build_research_dossier_archive_record(
        work_archive,
        dossier,
    )
    payload = asdict(record)
    payload["dossier"]["company_assessments"][0]["linkage"]["beta"] = float(
        "nan"
    )
    path = research_dossier_archive_path(record, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, allow_nan=True),
        encoding="utf-8",
    )

    assert not verify_research_dossier_archive(path)
    with pytest.raises(
        ValueError,
        match="non-finite JSON constant",
    ):
        read_research_dossier_archive(path)


def _rehash_archive_payload(payload):
    archive_payload = dict(payload)
    archive_payload["archive_record_hash"] = "0" * 64
    semantic = dict(archive_payload)
    semantic.pop("archive_record_hash")
    archive_payload["archive_record_hash"] = canonical_hash(semantic)
    return archive_payload


def test_reader_rejects_rehashed_false_dossier_status(tmp_path):
    work_archive, dossier = _company_archive_and_dossier()
    record = build_research_dossier_archive_record(
        work_archive,
        dossier,
    )
    payload = asdict(record)
    payload["dossier"]["status"] = "PARTIAL"
    nested = dict(payload["dossier"])
    nested["dossier_hash"] = "0" * 64
    semantic = dict(nested)
    semantic.pop("dossier_hash")
    nested["dossier_hash"] = canonical_hash(semantic)
    payload["dossier"] = nested
    payload["dossier_hash"] = nested["dossier_hash"]
    payload = _rehash_archive_payload(payload)
    path = (
        tmp_path
        / "dossiers"
        / "2026-09-19"
        / work_archive.work_order_hash
        / f"{payload['archive_record_hash']}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="inconsistent research dossier derived state",
    ):
        read_research_dossier_archive(path)


def test_verify_returns_false_for_missing_and_malformed_files(tmp_path):
    missing = tmp_path / "missing.json"
    assert not verify_research_work_order_archive(missing)
    assert not verify_research_dossier_archive(missing)

    malformed = tmp_path / "bad.json"
    malformed.write_text("{bad-json", encoding="utf-8")
    assert not verify_research_work_order_archive(malformed)
    assert not verify_research_dossier_archive(malformed)
