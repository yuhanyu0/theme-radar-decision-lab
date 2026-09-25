from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from enum import Enum
from itertools import pairwise

from .ledger import canonical_hash
from .research_execution import (
    CompanyLinkageStatus,
    ResearchDossierStatus,
    ResearchExecutionClosure,
    ResearchRequirement,
)
from .research_execution_archive import (
    ResearchDossierArchiveRecord,
    _parse_utc,
    _validate_dossier_archive_record,
)


class ResearchExecutionClosureTransition(str, Enum):
    OPEN_TO_OPEN = "OPEN_TO_OPEN"
    OPEN_TO_CLOSED = "OPEN_TO_CLOSED"
    CLOSED_TO_OPEN = "CLOSED_TO_OPEN"
    CLOSED_TO_CLOSED = "CLOSED_TO_CLOSED"


@dataclass(frozen=True)
class ResearchCompanyBurden:
    ticker: str
    independent_source_deficit: int
    linkage_status: CompanyLinkageStatus
    cautions: tuple[str, ...]


@dataclass(frozen=True)
class ResearchUnresolvedBurden:
    archive_record_hash: str
    unsatisfied_requirements: tuple[ResearchRequirement, ...]
    unresolved_finding_ids: tuple[str, ...]
    contradictions_present: bool
    independent_source_deficit: int
    company_burdens: tuple[ResearchCompanyBurden, ...]


@dataclass(frozen=True)
class ResearchProgressionOrphan:
    child_archive_record_hash: str
    missing_parent_archive_record_hash: str


@dataclass(frozen=True)
class ResearchProgressionFork:
    parent_archive_record_hash: str
    child_archive_record_hashes: tuple[str, ...]


@dataclass(frozen=True)
class ResearchProgressionSnapshot:
    archive_record_hash: str
    prior_dossier_archive_record_hash: str | None
    evidence_as_of: str
    closure: ResearchExecutionClosure
    status: ResearchDossierStatus
    burden: ResearchUnresolvedBurden


@dataclass(frozen=True)
class ResearchProgressionTransition:
    parent_archive_record_hash: str
    child_archive_record_hash: str
    parent_evidence_as_of: str
    child_evidence_as_of: str
    elapsed_seconds: float
    closure_transition: ResearchExecutionClosureTransition
    parent_status: ResearchDossierStatus
    child_status: ResearchDossierStatus
    became_complete: bool
    lost_complete_status: bool
    newly_satisfied_requirements: tuple[ResearchRequirement, ...]
    newly_unsatisfied_requirements: tuple[ResearchRequirement, ...]
    still_satisfied_requirements: tuple[ResearchRequirement, ...]
    still_unsatisfied_requirements: tuple[ResearchRequirement, ...]
    added_evidence_source_hashes: tuple[str, ...]
    removed_evidence_source_hashes: tuple[str, ...]
    added_finding_ids: tuple[str, ...]
    removed_finding_ids: tuple[str, ...]
    changed_finding_ids: tuple[str, ...]
    contradictions_before: bool
    contradictions_after: bool
    unresolved_before: bool
    unresolved_after: bool


@dataclass(frozen=True)
class ResearchProgressionTrajectory:
    archive_record_hashes: tuple[str, ...]
    start_archive_record_hash: str
    leaf_archive_record_hash: str
    starts_at_root: bool
    starts_at_orphan: bool
    lineage_complete: bool
    first_execution_closed_at: str | None
    first_complete_at: str | None
    time_from_source_to_first_execution_closure_seconds: float | None
    time_from_source_to_first_complete_seconds: float | None
    execution_reopen_count: int
    completion_loss_count: int


@dataclass(frozen=True)
class ResearchProgressionReport:
    work_order_archive_record_hash: str
    work_order_hash: str
    input_archive_record_hashes: tuple[str, ...]
    snapshots: tuple[ResearchProgressionSnapshot, ...]
    transitions: tuple[ResearchProgressionTransition, ...]
    roots: tuple[str, ...]
    orphans: tuple[ResearchProgressionOrphan, ...]
    forks: tuple[ResearchProgressionFork, ...]
    leaves: tuple[str, ...]
    trajectories: tuple[ResearchProgressionTrajectory, ...]
    progression_report_hash: str


def _report_payload_without_hash(
    report: ResearchProgressionReport,
) -> dict[str, object]:
    payload = asdict(report)
    payload.pop("progression_report_hash")
    return payload


def _closure_transition(
    parent: ResearchExecutionClosure,
    child: ResearchExecutionClosure,
) -> ResearchExecutionClosureTransition:
    return ResearchExecutionClosureTransition(
        f"{parent.value}_TO_{child.value}"
    )


def _build_burden(
    record: ResearchDossierArchiveRecord,
) -> ResearchUnresolvedBurden:
    dossier = record.dossier
    order = record.work_order_archive.work_order

    unresolved_finding_ids = tuple(
        finding.finding_id
        for finding in dossier.findings
        if finding.kind.value == "UNRESOLVED"
    )
    company_burdens = tuple(
        ResearchCompanyBurden(
            ticker=assessment.ticker,
            independent_source_deficit=max(
                0,
                order.minimum_independent_sources_per_company
                - assessment.independent_source_count,
            ),
            linkage_status=assessment.linkage_status,
            cautions=assessment.cautions,
        )
        for assessment in sorted(
            dossier.company_assessments,
            key=lambda item: item.ticker,
        )
    )
    return ResearchUnresolvedBurden(
        archive_record_hash=record.archive_record_hash,
        unsatisfied_requirements=dossier.unsatisfied_requirements,
        unresolved_finding_ids=unresolved_finding_ids,
        contradictions_present=dossier.contradictions_present,
        independent_source_deficit=max(
            0,
            order.minimum_independent_sources
            - dossier.independent_source_count,
        ),
        company_burdens=company_burdens,
    )


def _requirement_partition_transition(
    parent: ResearchDossierArchiveRecord,
    child: ResearchDossierArchiveRecord,
) -> tuple[
    tuple[ResearchRequirement, ...],
    tuple[ResearchRequirement, ...],
    tuple[ResearchRequirement, ...],
    tuple[ResearchRequirement, ...],
]:
    requirements = parent.work_order_archive.work_order.requirements
    parent_satisfied = set(parent.dossier.satisfied_requirements)
    child_satisfied = set(child.dossier.satisfied_requirements)

    newly_satisfied = tuple(
        item
        for item in requirements
        if item not in parent_satisfied and item in child_satisfied
    )
    newly_unsatisfied = tuple(
        item
        for item in requirements
        if item in parent_satisfied and item not in child_satisfied
    )
    still_satisfied = tuple(
        item
        for item in requirements
        if item in parent_satisfied and item in child_satisfied
    )
    still_unsatisfied = tuple(
        item
        for item in requirements
        if item not in parent_satisfied and item not in child_satisfied
    )
    return (
        newly_satisfied,
        newly_unsatisfied,
        still_satisfied,
        still_unsatisfied,
    )


def _build_transition(
    parent: ResearchDossierArchiveRecord,
    child: ResearchDossierArchiveRecord,
) -> ResearchProgressionTransition:
    (
        newly_satisfied,
        newly_unsatisfied,
        still_satisfied,
        still_unsatisfied,
    ) = _requirement_partition_transition(parent, child)

    parent_evidence_hashes = {
        binding.evidence.source_hash
        for binding in parent.dossier.evidence_bindings
    }
    child_evidence_hashes = {
        binding.evidence.source_hash
        for binding in child.dossier.evidence_bindings
    }

    parent_findings = {
        finding.finding_id: finding
        for finding in parent.dossier.findings
    }
    child_findings = {
        finding.finding_id: finding
        for finding in child.dossier.findings
    }
    parent_ids = set(parent_findings)
    child_ids = set(child_findings)
    changed_ids = tuple(
        sorted(
            finding_id
            for finding_id in parent_ids & child_ids
            if parent_findings[finding_id]
            != child_findings[finding_id]
        )
    )

    parent_status = parent.dossier.status
    child_status = child.dossier.status
    parent_time = _parse_utc(parent.evidence_as_of)
    child_time = _parse_utc(child.evidence_as_of)

    return ResearchProgressionTransition(
        parent_archive_record_hash=parent.archive_record_hash,
        child_archive_record_hash=child.archive_record_hash,
        parent_evidence_as_of=parent.evidence_as_of,
        child_evidence_as_of=child.evidence_as_of,
        elapsed_seconds=(child_time - parent_time).total_seconds(),
        closure_transition=_closure_transition(
            parent.dossier.closure,
            child.dossier.closure,
        ),
        parent_status=parent_status,
        child_status=child_status,
        became_complete=(
            parent_status is not ResearchDossierStatus.COMPLETE
            and child_status is ResearchDossierStatus.COMPLETE
        ),
        lost_complete_status=(
            parent_status is ResearchDossierStatus.COMPLETE
            and child_status is not ResearchDossierStatus.COMPLETE
        ),
        newly_satisfied_requirements=newly_satisfied,
        newly_unsatisfied_requirements=newly_unsatisfied,
        still_satisfied_requirements=still_satisfied,
        still_unsatisfied_requirements=still_unsatisfied,
        added_evidence_source_hashes=tuple(
            sorted(child_evidence_hashes - parent_evidence_hashes)
        ),
        removed_evidence_source_hashes=tuple(
            sorted(parent_evidence_hashes - child_evidence_hashes)
        ),
        added_finding_ids=tuple(sorted(child_ids - parent_ids)),
        removed_finding_ids=tuple(sorted(parent_ids - child_ids)),
        changed_finding_ids=changed_ids,
        contradictions_before=parent.dossier.contradictions_present,
        contradictions_after=child.dossier.contradictions_present,
        unresolved_before=parent.dossier.unresolved_present,
        unresolved_after=child.dossier.unresolved_present,
    )


def _maximal_paths(
    start_hash: str,
    children: dict[str, list[str]],
) -> tuple[tuple[str, ...], ...]:
    paths: list[tuple[str, ...]] = []

    def visit(
        current_hash: str,
        prefix: tuple[str, ...],
    ) -> None:
        next_hashes = children[current_hash]
        current_path = prefix + (current_hash,)
        if not next_hashes:
            paths.append(current_path)
            return
        for child_hash in next_hashes:
            visit(child_hash, current_path)

    visit(start_hash, ())
    return tuple(paths)


def _build_trajectory(
    archive_hashes: tuple[str, ...],
    *,
    nodes: dict[str, ResearchDossierArchiveRecord],
    starts_at_root: bool,
    starts_at_orphan: bool,
) -> ResearchProgressionTrajectory:
    records = tuple(nodes[archive_hash] for archive_hash in archive_hashes)
    first_closed = next(
        (
            record
            for record in records
            if record.dossier.closure
            is ResearchExecutionClosure.CLOSED
        ),
        None,
    )
    first_complete = next(
        (
            record
            for record in records
            if record.dossier.status
            is ResearchDossierStatus.COMPLETE
        ),
        None,
    )

    reopen_count = 0
    completion_loss_count = 0
    for parent, child in pairwise(records):
        if (
            parent.dossier.closure
            is ResearchExecutionClosure.CLOSED
            and child.dossier.closure
            is ResearchExecutionClosure.OPEN
        ):
            reopen_count += 1
        if (
            parent.dossier.status
            is ResearchDossierStatus.COMPLETE
            and child.dossier.status
            is not ResearchDossierStatus.COMPLETE
        ):
            completion_loss_count += 1

    source_as_of = _parse_utc(
        records[0].work_order_archive.source_cycle_as_of
    )
    closure_seconds = None
    complete_seconds = None
    if starts_at_root:
        if first_closed is not None:
            closure_seconds = (
                _parse_utc(first_closed.evidence_as_of)
                - source_as_of
            ).total_seconds()
        if first_complete is not None:
            complete_seconds = (
                _parse_utc(first_complete.evidence_as_of)
                - source_as_of
            ).total_seconds()

    return ResearchProgressionTrajectory(
        archive_record_hashes=archive_hashes,
        start_archive_record_hash=archive_hashes[0],
        leaf_archive_record_hash=archive_hashes[-1],
        starts_at_root=starts_at_root,
        starts_at_orphan=starts_at_orphan,
        lineage_complete=starts_at_root,
        first_execution_closed_at=(
            None
            if first_closed is None
            else first_closed.evidence_as_of
        ),
        first_complete_at=(
            None
            if first_complete is None
            else first_complete.evidence_as_of
        ),
        time_from_source_to_first_execution_closure_seconds=(
            closure_seconds
        ),
        time_from_source_to_first_complete_seconds=complete_seconds,
        execution_reopen_count=reopen_count,
        completion_loss_count=completion_loss_count,
    )


def evaluate_research_progression(
    records: Sequence[ResearchDossierArchiveRecord],
) -> ResearchProgressionReport:
    if isinstance(records, (str, bytes)) or not isinstance(
        records,
        Sequence,
    ):
        raise TypeError(
            "research progression records must be a sequence"
        )
    if not records:
        raise ValueError(
            "research progression records must be non-empty"
        )

    validated = tuple(records)
    for record in validated:
        if not isinstance(record, ResearchDossierArchiveRecord):
            raise TypeError(
                "research progression records must be dossier archives"
            )
        _validate_dossier_archive_record(record)

    archive_hashes = tuple(
        record.archive_record_hash for record in validated
    )
    if len(set(archive_hashes)) != len(archive_hashes):
        raise ValueError(
            "duplicate research progression archive identity"
        )

    work_order_archive = validated[0].work_order_archive
    for record in validated[1:]:
        if (
            record.work_order_archive.archive_record_hash
            != work_order_archive.archive_record_hash
            or record.work_order_archive != work_order_archive
        ):
            raise ValueError(
                "research progression work order archive mismatch"
            )

    nodes = {
        record.archive_record_hash: record
        for record in validated
    }
    children: dict[str, list[str]] = {
        archive_hash: []
        for archive_hash in nodes
    }
    roots: list[str] = []
    orphans: list[ResearchProgressionOrphan] = []
    transitions: list[ResearchProgressionTransition] = []

    for child_hash, child in nodes.items():
        parent_hash = child.prior_dossier_archive_record_hash
        if parent_hash is None:
            roots.append(child_hash)
            continue

        parent = nodes.get(parent_hash)
        if parent is None:
            orphans.append(
                ResearchProgressionOrphan(
                    child_archive_record_hash=child_hash,
                    missing_parent_archive_record_hash=parent_hash,
                )
            )
            continue

        if _parse_utc(parent.evidence_as_of) >= _parse_utc(
            child.evidence_as_of
        ):
            raise ValueError(
                "resolved research dossier parent must be strictly earlier"
            )

        children[parent_hash].append(child_hash)
        transitions.append(
            _build_transition(parent, child)
        )

    for child_hashes in children.values():
        child_hashes.sort()

    forks = tuple(
        ResearchProgressionFork(
            parent_archive_record_hash=parent_hash,
            child_archive_record_hashes=tuple(child_hashes),
        )
        for parent_hash, child_hashes in sorted(children.items())
        if len(child_hashes) > 1
    )
    leaves = tuple(
        sorted(
            archive_hash
            for archive_hash, child_hashes in children.items()
            if not child_hashes
        )
    )

    snapshots = tuple(
        ResearchProgressionSnapshot(
            archive_record_hash=record.archive_record_hash,
            prior_dossier_archive_record_hash=(
                record.prior_dossier_archive_record_hash
            ),
            evidence_as_of=record.evidence_as_of,
            closure=record.dossier.closure,
            status=record.dossier.status,
            burden=_build_burden(record),
        )
        for record in sorted(
            validated,
            key=lambda item: (
                _parse_utc(item.evidence_as_of),
                item.archive_record_hash,
            ),
        )
    )

    transitions_tuple = tuple(
        sorted(
            transitions,
            key=lambda item: (
                _parse_utc(item.parent_evidence_as_of),
                _parse_utc(item.child_evidence_as_of),
                item.parent_archive_record_hash,
                item.child_archive_record_hash,
            ),
        )
    )
    orphans_tuple = tuple(
        sorted(
            orphans,
            key=lambda item: (
                item.child_archive_record_hash,
                item.missing_parent_archive_record_hash,
            ),
        )
    )

    trajectories: list[ResearchProgressionTrajectory] = []
    for root_hash in sorted(roots):
        for path in _maximal_paths(root_hash, children):
            trajectories.append(
                _build_trajectory(
                    path,
                    nodes=nodes,
                    starts_at_root=True,
                    starts_at_orphan=False,
                )
            )
    for orphan in orphans_tuple:
        for path in _maximal_paths(
            orphan.child_archive_record_hash,
            children,
        ):
            trajectories.append(
                _build_trajectory(
                    path,
                    nodes=nodes,
                    starts_at_root=False,
                    starts_at_orphan=True,
                )
            )
    trajectories_tuple = tuple(
        sorted(
            trajectories,
            key=lambda item: item.archive_record_hashes,
        )
    )

    seed = ResearchProgressionReport(
        work_order_archive_record_hash=(
            work_order_archive.archive_record_hash
        ),
        work_order_hash=work_order_archive.work_order_hash,
        input_archive_record_hashes=tuple(sorted(archive_hashes)),
        snapshots=snapshots,
        transitions=transitions_tuple,
        roots=tuple(sorted(roots)),
        orphans=orphans_tuple,
        forks=forks,
        leaves=leaves,
        trajectories=trajectories_tuple,
        progression_report_hash="0" * 64,
    )
    return replace(
        seed,
        progression_report_hash=canonical_hash(
            _report_payload_without_hash(seed)
        ),
    )
