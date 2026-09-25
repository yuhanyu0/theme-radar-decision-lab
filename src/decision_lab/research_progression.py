from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace

from .ledger import canonical_hash
from .research_execution import (
    ResearchDossierStatus,
    ResearchExecutionClosure,
)
from .research_execution_archive import (
    ResearchDossierArchiveRecord,
    _parse_utc,
    _validate_dossier_archive_record,
)


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


@dataclass(frozen=True)
class ResearchProgressionTransition:
    parent_archive_record_hash: str
    child_archive_record_hash: str


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
    progression_report_hash: str


def _report_payload_without_hash(
    report: ResearchProgressionReport,
) -> dict[str, object]:
    payload = asdict(report)
    payload.pop("progression_report_hash")
    return payload


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
            ResearchProgressionTransition(
                parent_archive_record_hash=parent_hash,
                child_archive_record_hash=child_hash,
            )
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
                _parse_utc(
                    nodes[item.parent_archive_record_hash].evidence_as_of
                ),
                _parse_utc(
                    nodes[item.child_archive_record_hash].evidence_as_of
                ),
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
        progression_report_hash="0" * 64,
    )
    return replace(
        seed,
        progression_report_hash=canonical_hash(
            _report_payload_without_hash(seed)
        ),
    )
