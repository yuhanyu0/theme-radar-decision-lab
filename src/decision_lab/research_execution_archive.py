from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import Enum
import json
import os
from math import isfinite
from pathlib import Path

from .evidence import SOURCE_PRIORITY
from .hierarchical import HierarchicalLinkageResult
from .ledger import canonical_hash
from .linkage import LinkageResult
from .replay_archive import ReplayArchiveRecord, build_replay_archive_record
from .replay_cohort import RoutingIntent, evaluate_replay_cohort
from .research_budget import ResearchTier
from .research_execution import (
    CompanyLinkageStatus,
    CompanyResearchAssessment,
    FrozenResearchEvidence,
    HierarchicalLinkageSnapshot,
    NormalizedCompanyField,
    NormalizedCompanySnapshot,
    ResearchAuthorization,
    ResearchDossier,
    ResearchDossierStatus,
    ResearchEvidenceBinding,
    ResearchEvidenceDirection,
    ResearchExecutionClosure,
    ResearchFinding,
    ResearchFindingKind,
    ResearchMode,
    ResearchTarget,
    ResearchRequirement,
    ResearchRequirementScope,
    ResearchWorkOrder,
    ResearchWorkOrderPolicy,
    _DOSSIER_LIMITATIONS,
    _linkage_status,
    _CONTRADICTION_QUESTIONS,
    _build_requirements,
    _normalize_policy,
    _validate_work_order_hash,
)

SCHEMA_VERSION = "0.1"
PRODUCER = "theme-radar-decision-lab/research-execution-archive@0.1"
WORK_ORDER_CONTENT_TYPE = "research_work_order"
DOSSIER_CONTENT_TYPE = "research_dossier"


class ResearchArchiveDestinationVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"


@dataclass(frozen=True)
class ResearchArchiveWriteResult:
    path: Path
    created: bool
    content_hash: str
    archive_record_hash: str


@dataclass(frozen=True)
class ResearchWorkOrderArchiveRecord:
    schema_version: str
    content_type: str
    producer: str
    source_cycle_as_of: str
    source_replay_archive_record_hash: str
    source_replay_result_hash: str
    work_order_hash: str
    work_order_policy: ResearchWorkOrderPolicy
    work_order: ResearchWorkOrder
    archive_record_hash: str


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    if "T" not in value and " " not in value:
        dt = dt.replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )
    return dt


def _cycle_date(value: str) -> str:
    return _parse_utc(value).date().isoformat()


def _validate_sha256(value: str, *, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"invalid {field_name}")


def _validate_work_order_policy(
    order: ResearchWorkOrder,
    policy: ResearchWorkOrderPolicy,
) -> ResearchWorkOrderPolicy:
    try:
        normalized = _normalize_policy(policy)
        _validate_work_order_hash(order)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid research work order") from exc

    if (
        order.targets
        != tuple(sorted(order.targets, key=lambda item: item.ticker))
        or any(
            not target.ticker
            or target.ticker != target.ticker.upper()
            for target in order.targets
        )
        or (
            order.source_forced_review
            and order.contradiction_questions
            != _CONTRADICTION_QUESTIONS
        )
        or (
            not order.source_forced_review
            and order.contradiction_questions
        )
    ):
        raise ValueError("invalid research work order")

    if canonical_hash(asdict(normalized)) != order.policy_hash:
        raise ValueError("research work order policy mismatch")
    if (
        normalized.minimum_independent_sources
        != order.minimum_independent_sources
        or normalized.minimum_independent_sources_per_company
        != order.minimum_independent_sources_per_company
    ):
        raise ValueError("research work order policy mismatch")

    try:
        expected_requirements = _build_requirements(
            mode=order.research_mode,
            targets=order.targets,
            adapter_name=order.evidence_adapter,
            policy=normalized,
        )
    except (TypeError, ValueError, AssertionError) as exc:
        raise ValueError("research work order policy mismatch") from exc

    if expected_requirements != order.requirements:
        raise ValueError("research work order policy mismatch")
    return normalized


def _validate_source_replay(
    replay_archive: ReplayArchiveRecord,
) -> None:
    try:
        rebuilt = build_replay_archive_record(
            replay_archive.replay_result
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "invalid source replay archive record"
        ) from exc
    if rebuilt != replay_archive:
        raise ValueError("invalid source replay archive record")


def _validate_replay_work_order_lineage(
    replay_archive: ReplayArchiveRecord,
    order: ResearchWorkOrder,
) -> None:
    if (
        order.source_archive_record_hash
        != replay_archive.archive_record_hash
        or order.source_replay_result_hash
        != replay_archive.replay_result_hash
        or order.source_cycle_as_of
        != replay_archive.cycle_as_of
    ):
        raise ValueError(
            "research work order replay lineage mismatch"
        )

    cohort = evaluate_replay_cohort(
        (replay_archive,),
        horizons=(1,),
    )
    matches = [
        item
        for item in cohort.transitions
        if item.theme_id == order.theme_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "research work order replay lineage mismatch"
        )
    transition = matches[0]
    if (
        transition.routing_intent
        is not order.source_routing_intent
        or transition.source_registered
        != order.source_registered
        or transition.source_tier
        is not order.source_allocated_tier
        or transition.source_forced_review
        != order.source_forced_review
    ):
        raise ValueError(
            "research work order replay lineage mismatch"
        )


def _work_order_archive_payload_without_hash(
    record: ResearchWorkOrderArchiveRecord,
) -> dict[str, object]:
    payload = asdict(record)
    payload.pop("archive_record_hash")
    return payload


def _validate_work_order_archive_record(
    record: ResearchWorkOrderArchiveRecord,
) -> None:
    if (
        record.schema_version != SCHEMA_VERSION
        or record.content_type != WORK_ORDER_CONTENT_TYPE
        or record.producer != PRODUCER
    ):
        raise ValueError(
            "unsupported research work-order archive contract"
        )

    for field_name, value in (
        (
            "source replay archive record hash",
            record.source_replay_archive_record_hash,
        ),
        (
            "source replay result hash",
            record.source_replay_result_hash,
        ),
        ("work order hash", record.work_order_hash),
        (
            "research work-order archive hash",
            record.archive_record_hash,
        ),
    ):
        _validate_sha256(value, field_name=field_name)

    normalized_policy = _validate_work_order_policy(
        record.work_order,
        record.work_order_policy,
    )
    if normalized_policy != record.work_order_policy:
        raise ValueError("research work order policy mismatch")

    if (
        record.source_cycle_as_of
        != record.work_order.source_cycle_as_of
        or record.source_replay_archive_record_hash
        != record.work_order.source_archive_record_hash
        or record.source_replay_result_hash
        != record.work_order.source_replay_result_hash
        or record.work_order_hash
        != record.work_order.work_order_hash
    ):
        raise ValueError(
            "research work-order archive nested identity mismatch"
        )

    expected = canonical_hash(
        _work_order_archive_payload_without_hash(record)
    )
    if expected != record.archive_record_hash:
        raise ValueError(
            "research work-order archive hash mismatch"
        )


def build_research_work_order_archive_record(
    replay_archive: ReplayArchiveRecord,
    work_order: ResearchWorkOrder,
    *,
    work_order_policy: ResearchWorkOrderPolicy,
) -> ResearchWorkOrderArchiveRecord:
    _validate_source_replay(replay_archive)
    normalized_policy = _validate_work_order_policy(
        work_order,
        work_order_policy,
    )
    _validate_replay_work_order_lineage(
        replay_archive,
        work_order,
    )

    seed = ResearchWorkOrderArchiveRecord(
        schema_version=SCHEMA_VERSION,
        content_type=WORK_ORDER_CONTENT_TYPE,
        producer=PRODUCER,
        source_cycle_as_of=work_order.source_cycle_as_of,
        source_replay_archive_record_hash=(
            replay_archive.archive_record_hash
        ),
        source_replay_result_hash=(
            replay_archive.replay_result_hash
        ),
        work_order_hash=work_order.work_order_hash,
        work_order_policy=normalized_policy,
        work_order=work_order,
        archive_record_hash="0" * 64,
    )
    record = replace(
        seed,
        archive_record_hash=canonical_hash(
            _work_order_archive_payload_without_hash(seed)
        ),
    )
    _validate_work_order_archive_record(record)
    return record


def research_work_order_archive_path(
    record: ResearchWorkOrderArchiveRecord,
    archive_root: str | Path,
) -> Path:
    return (
        Path(archive_root)
        / "work_orders"
        / _cycle_date(record.source_cycle_as_of)
        / f"{record.work_order_hash}.json"
    )



@dataclass(frozen=True)
class ResearchDossierArchiveRecord:
    schema_version: str
    content_type: str
    producer: str
    source_cycle_as_of: str
    evidence_as_of: str
    work_order_archive: ResearchWorkOrderArchiveRecord
    prior_dossier_archive_record_hash: str | None
    dossier_hash: str
    dossier: ResearchDossier
    archive_record_hash: str


def _validate_frozen_evidence(
    binding: ResearchEvidenceBinding,
    *,
    order: ResearchWorkOrder,
    evidence_as_of: datetime,
) -> None:
    evidence = binding.evidence
    _validate_sha256(
        evidence.source_hash,
        field_name="research evidence source hash",
    )
    _validate_sha256(
        evidence.payload_hash,
        field_name="research evidence payload hash",
    )
    if not evidence.source_ref.strip():
        raise ValueError("invalid research evidence source_ref")
    if evidence.source_type not in SOURCE_PRIORITY:
        raise ValueError("unsupported research evidence source_type")
    if not isinstance(evidence.is_observed_fact, bool):
        raise TypeError(
            "research evidence is_observed_fact must be bool"
        )
    if not isinstance(binding.independent, bool):
        raise TypeError("research evidence independent must be bool")
    if not isinstance(
        binding.direction,
        ResearchEvidenceDirection,
    ):
        raise TypeError(
            "research evidence direction must be ResearchEvidenceDirection"
        )
    if (
        binding.independent
        and (
            evidence.source_type == "radar_model_output"
            or not evidence.is_observed_fact
        )
    ):
        raise ValueError(
            "model or inferred evidence cannot be independent"
        )

    if (
        not binding.dimensions
        or binding.dimensions
        != tuple(sorted(binding.dimensions))
        or len(set(binding.dimensions)) != len(binding.dimensions)
        or any(
            not value or value != value.strip()
            for value in binding.dimensions
        )
    ):
        raise ValueError("invalid research evidence dimensions")

    for value in (
        evidence.observed_at,
        evidence.market_asof,
        evidence.retrieved_at,
    ):
        if (
            value is not None
            and _parse_utc(value) > evidence_as_of
        ):
            raise ValueError(
                "research evidence exceeds dossier evidence_as_of"
            )

    targets = {target.ticker for target in order.targets}
    if (
        evidence.theme is not None
        and evidence.theme != order.theme_id
    ):
        raise ValueError(
            "research evidence outside work-order scope"
        )
    if (
        evidence.ticker is not None
        and evidence.ticker not in targets
    ):
        raise ValueError(
            "research evidence outside work-order scope"
        )
    if evidence.theme is None and evidence.ticker is None:
        raise ValueError(
            "research evidence outside work-order scope"
        )

    if order.research_mode is ResearchMode.THEME_REASSESSMENT:
        if (
            binding.target_ticker is not None
            or evidence.ticker is not None
        ):
            raise ValueError(
                "research evidence outside work-order scope"
            )
    else:
        if binding.target_ticker not in targets:
            raise ValueError(
                "research evidence outside work-order scope"
            )
        if (
            evidence.ticker is not None
            and evidence.ticker != binding.target_ticker
        ):
            raise ValueError("research evidence target mismatch")


def _validate_simple_linkage(
    linkage: LinkageResult,
    *,
    ticker: str,
) -> None:
    if linkage.ticker != ticker:
        raise ValueError("research linkage ticker mismatch")
    for field_name in (
        "correlation",
        "beta",
        "r2",
        "residual_mean",
        "residual_vol",
        "beta_stability",
        "decoupling_score",
    ):
        value = getattr(linkage, field_name)
        if (
            value is not None
            and not isfinite(float(value))
        ):
            raise ValueError(
                "research linkage numeric field must be finite"
            )


def _validate_hierarchical_snapshot(
    snapshot: HierarchicalLinkageSnapshot,
    *,
    ticker: str,
) -> None:
    if snapshot.target != ticker:
        raise ValueError("research linkage ticker mismatch")
    for field_name in (
        "theme_correlation",
        "theme_beta",
        "r2",
        "incremental_theme_r2",
        "residual_mean",
        "residual_vol",
    ):
        value = getattr(snapshot, field_name)
        if (
            value is not None
            and not isfinite(float(value))
        ):
            raise ValueError(
                "research linkage numeric field must be finite"
            )
    if (
        snapshot.coefficients
        != tuple(sorted(snapshot.coefficients))
        or len(
            {name for name, _ in snapshot.coefficients}
        )
        != len(snapshot.coefficients)
        or any(
            not name or not isfinite(float(value))
            for name, value in snapshot.coefficients
        )
    ):
        raise ValueError(
            "invalid research hierarchical linkage coefficients"
        )
    _validate_sha256(
        snapshot.source_payload_hash,
        field_name="hierarchical linkage source payload hash",
    )
    reconstructed = HierarchicalLinkageResult(
        target=snapshot.target,
        status=snapshot.status,
        window=snapshot.window,
        observations=snapshot.observations,
        theme_correlation=snapshot.theme_correlation,
        theme_beta=snapshot.theme_beta,
        r2=snapshot.r2,
        incremental_theme_r2=snapshot.incremental_theme_r2,
        residual_mean=snapshot.residual_mean,
        residual_vol=snapshot.residual_vol,
        circularity_warning=snapshot.circularity_warning,
        missing_controls=snapshot.missing_controls,
        coefficients=dict(snapshot.coefficients),
    )
    if (
        canonical_hash(asdict(reconstructed))
        != snapshot.source_payload_hash
    ):
        raise ValueError(
            "hierarchical linkage source payload hash mismatch"
        )


def _expected_company_cautions(
    assessment: CompanyResearchAssessment,
    *,
    order: ResearchWorkOrder,
) -> tuple[str, ...]:
    cautions: list[str] = []
    if (
        assessment.linkage_status
        is CompanyLinkageStatus.COVERAGE_PENDING
    ):
        cautions.append("linkage coverage pending")
    elif (
        assessment.linkage_status
        is CompanyLinkageStatus.CIRCULARITY_WARNING
    ):
        cautions.append("linkage circularity warning")
    if (
        assessment.independent_source_count
        < order.minimum_independent_sources_per_company
    ):
        cautions.append("independent source minimum not met")
    return tuple(cautions)


def _validate_company_assessments(
    dossier: ResearchDossier,
    *,
    order: ResearchWorkOrder,
) -> None:
    if order.research_mode is ResearchMode.THEME_REASSESSMENT:
        if dossier.company_assessments:
            raise ValueError(
                "inconsistent research company assessment"
            )
        return

    targets = tuple(
        target.ticker for target in order.targets
    )
    if tuple(
        item.ticker for item in dossier.company_assessments
    ) != targets:
        raise ValueError(
            "inconsistent research company assessment"
        )

    for assessment in dossier.company_assessments:
        bindings = tuple(
            item
            for item in dossier.evidence_bindings
            if item.target_ticker == assessment.ticker
        )
        expected_hashes = tuple(
            sorted(
                item.evidence.source_hash
                for item in bindings
            )
        )
        independent_refs = {
            item.evidence.source_ref
            for item in bindings
            if item.independent
        }
        if (
            assessment.evidence_source_hashes
            != expected_hashes
            or assessment.independent_source_count
            != len(independent_refs)
        ):
            raise ValueError(
                "inconsistent research company assessment"
            )

        snapshot = assessment.normalized_evidence
        if snapshot is None:
            expected_dimensions: tuple[str, ...] = ()
        else:
            if (
                snapshot.ticker != assessment.ticker
                or snapshot.adapter_name
                != order.evidence_adapter
            ):
                raise ValueError(
                    "inconsistent research company assessment"
                )
            _validate_sha256(
                snapshot.normalized_payload_hash,
                field_name="normalized company payload hash",
            )
            normalized_as_of = _parse_utc(snapshot.as_of)
            if (
                normalized_as_of.isoformat()
                != snapshot.as_of
                or normalized_as_of
                < _parse_utc(order.source_cycle_as_of)
                or normalized_as_of
                > _parse_utc(dossier.evidence_as_of)
                or not snapshot.source_coverage
            ):
                raise ValueError(
                    "inconsistent research company assessment"
                )
            all_evidence_hashes = {
                item.evidence.source_hash
                for item in dossier.evidence_bindings
            }
            if (
                snapshot.provenance
                != tuple(sorted(snapshot.provenance))
                or len(set(snapshot.provenance))
                != len(snapshot.provenance)
                or any(
                    digest not in all_evidence_hashes
                    for digest in snapshot.provenance
                )
            ):
                raise ValueError(
                    "inconsistent research company assessment"
                )
            names = tuple(
                field.name for field in snapshot.fields
            )
            if (
                names != tuple(sorted(names))
                or len(set(names)) != len(names)
                or any(not name for name in names)
            ):
                raise ValueError(
                    "inconsistent research company assessment"
                )
            for field in snapshot.fields:
                if (
                    isinstance(field.value, bool)
                    or not isinstance(
                        field.value,
                        (int, float, str),
                    )
                ):
                    raise TypeError(
                        "invalid normalized company field value"
                    )
                if (
                    isinstance(field.value, float)
                    and not isfinite(field.value)
                ):
                    raise ValueError(
                        "invalid normalized company field value"
                    )
            expected_dimensions = names

        if (
            assessment.covered_dimensions
            != expected_dimensions
        ):
            raise ValueError(
                "inconsistent research company assessment"
            )

        if assessment.linkage is not None:
            _validate_simple_linkage(
                assessment.linkage,
                ticker=assessment.ticker,
            )
        if assessment.hierarchical_linkage is not None:
            _validate_hierarchical_snapshot(
                assessment.hierarchical_linkage,
                ticker=assessment.ticker,
            )
        expected_status = _linkage_status(
            assessment.linkage,
            assessment.hierarchical_linkage,
        )
        if (
            assessment.linkage_status is not expected_status
            or assessment.cautions
            != _expected_company_cautions(
                assessment,
                order=order,
            )
        ):
            raise ValueError(
                "inconsistent research company assessment"
            )


def _validate_findings(
    dossier: ResearchDossier,
    *,
    order: ResearchWorkOrder,
) -> None:
    evidence = {
        item.evidence.source_hash: item.evidence
        for item in dossier.evidence_bindings
    }
    if len(evidence) != len(dossier.evidence_bindings):
        raise ValueError(
            "duplicate research evidence source hash"
        )
    if dossier.findings != tuple(
        sorted(
            dossier.findings,
            key=lambda item: item.finding_id,
        )
    ):
        raise ValueError(
            "invalid research finding ordering"
        )

    seen: set[str] = set()
    targets = {target.ticker for target in order.targets}
    for finding in dossier.findings:
        if not isinstance(
            finding.kind,
            ResearchFindingKind,
        ):
            raise TypeError(
                "research finding kind must be ResearchFindingKind"
            )
        if (
            finding.direction is not None
            and not isinstance(
                finding.direction,
                ResearchEvidenceDirection,
            )
        ):
            raise TypeError(
                "research finding direction must be ResearchEvidenceDirection"
            )
        if (
            not finding.finding_id
            or finding.finding_id
            != finding.finding_id.strip()
            or finding.finding_id in seen
            or not finding.dimension
            or finding.dimension
            != finding.dimension.strip()
            or not finding.statement
            or finding.statement
            != finding.statement.strip()
        ):
            raise ValueError("invalid research finding")
        seen.add(finding.finding_id)
        if (
            finding.target_ticker is not None
            and finding.target_ticker not in targets
        ):
            raise ValueError("invalid research finding")
        if (
            finding.evidence_source_hashes
            != tuple(
                sorted(finding.evidence_source_hashes)
            )
            or len(set(finding.evidence_source_hashes))
            != len(finding.evidence_source_hashes)
            or any(
                digest not in evidence
                for digest
                in finding.evidence_source_hashes
            )
        ):
            raise ValueError(
                "invalid research finding evidence"
            )

        if finding.kind is ResearchFindingKind.UNRESOLVED:
            if finding.direction is not None:
                raise ValueError(
                    "invalid unresolved research finding"
                )
        else:
            if (
                finding.direction is None
                or not finding.evidence_source_hashes
            ):
                raise ValueError("invalid research finding")
            if (
                finding.kind
                is ResearchFindingKind.OBSERVED_SYNTHESIS
                and any(
                    not evidence[digest].is_observed_fact
                    for digest
                    in finding.evidence_source_hashes
                )
            ):
                raise ValueError(
                    "invalid observed research finding"
                )

        if finding.target_ticker is not None:
            for digest in finding.evidence_source_hashes:
                evidence_ticker = evidence[digest].ticker
                if evidence_ticker not in (
                    None,
                    finding.target_ticker,
                ):
                    raise ValueError(
                        "research finding cites another target"
                    )


def _requirement_satisfied(
    requirement: ResearchRequirement,
    *,
    dossier: ResearchDossier,
    assessment_by_ticker: Mapping[
        str,
        CompanyResearchAssessment,
    ],
) -> bool:
    if (
        requirement.scope
        is ResearchRequirementScope.THEME_EVIDENCE
    ):
        return any(
            item.target_ticker is None
            and requirement.dimension
            in item.dimensions
            for item in dossier.evidence_bindings
        )

    target = requirement.target_ticker
    if target is None:
        return False
    assessment = assessment_by_ticker[target]
    if (
        requirement.scope
        is ResearchRequirementScope.COMPANY_LINKAGE
    ):
        return (
            assessment.linkage_status
            is CompanyLinkageStatus.USABLE
        )

    return (
        any(
            item.target_ticker == target
            and requirement.dimension in item.dimensions
            for item in dossier.evidence_bindings
        )
        and assessment.normalized_evidence is not None
        and requirement.dimension
        in assessment.covered_dimensions
    )


def _expected_dossier_status(
    dossier: ResearchDossier,
    *,
    order: ResearchWorkOrder,
) -> ResearchDossierStatus:
    assessment_by_ticker = {
        item.ticker: item
        for item in dossier.company_assessments
    }
    unsatisfied = tuple(
        item
        for item in order.requirements
        if not _requirement_satisfied(
            item,
            dossier=dossier,
            assessment_by_ticker=assessment_by_ticker,
        )
    )
    independent_refs = {
        item.evidence.source_ref
        for item in dossier.evidence_bindings
        if item.independent
    }
    company_complete = (
        order.research_mode
        is ResearchMode.THEME_REASSESSMENT
        or all(
            item.normalized_evidence is not None
            and item.independent_source_count
            >= order.minimum_independent_sources_per_company
            for item in dossier.company_assessments
        )
    )
    complete = (
        not unsatisfied
        and len(independent_refs)
        >= order.minimum_independent_sources
        and company_complete
    )
    if complete:
        return ResearchDossierStatus.COMPLETE
    if (
        dossier.closure
        is ResearchExecutionClosure.CLOSED
    ):
        return (
            ResearchDossierStatus.BLOCKED_INSUFFICIENT_EVIDENCE
        )

    has_activity = bool(
        dossier.evidence_bindings or dossier.findings
    )
    has_activity = has_activity or any(
        item.normalized_evidence is not None
        or item.linkage_status
        is not CompanyLinkageStatus.NOT_PROVIDED
        for item in dossier.company_assessments
    )
    return (
        ResearchDossierStatus.PARTIAL
        if has_activity
        else ResearchDossierStatus.NOT_STARTED
    )


def _dossier_payload_without_hash(
    dossier: ResearchDossier,
) -> dict[str, object]:
    payload = asdict(dossier)
    payload.pop("dossier_hash")
    return payload


def _validate_dossier(
    dossier: ResearchDossier,
    *,
    order: ResearchWorkOrder,
) -> None:
    if not isinstance(
        dossier.closure,
        ResearchExecutionClosure,
    ):
        raise TypeError(
            "research dossier closure must be ResearchExecutionClosure"
        )
    if not isinstance(
        dossier.status,
        ResearchDossierStatus,
    ):
        raise TypeError(
            "research dossier status must be ResearchDossierStatus"
        )
    if not isinstance(
        dossier.research_mode,
        ResearchMode,
    ):
        raise TypeError(
            "research dossier mode must be ResearchMode"
        )
    if (
        dossier.schema_version != "0.1"
        or dossier.work_order_hash
        != order.work_order_hash
        or dossier.source_archive_record_hash
        != order.source_archive_record_hash
        or dossier.source_cycle_as_of
        != order.source_cycle_as_of
        or dossier.theme_id != order.theme_id
        or dossier.research_mode
        is not order.research_mode
        or tuple(dossier.limitations)
        != tuple(_DOSSIER_LIMITATIONS)
    ):
        raise ValueError(
            "research dossier work-order lineage mismatch"
        )

    _validate_sha256(
        dossier.input_hash,
        field_name="research dossier input hash",
    )
    _validate_sha256(
        dossier.dossier_hash,
        field_name="research dossier hash",
    )
    evidence_as_of = _parse_utc(dossier.evidence_as_of)
    if evidence_as_of.isoformat() != dossier.evidence_as_of:
        raise ValueError(
            "research dossier evidence_as_of must be canonical UTC"
        )
    if evidence_as_of < _parse_utc(
        dossier.source_cycle_as_of
    ):
        raise ValueError(
            "research dossier evidence_as_of precedes source cycle"
        )

    if dossier.evidence_bindings != tuple(
        sorted(
            dossier.evidence_bindings,
            key=lambda item: (
                item.evidence.source_hash,
                item.target_ticker or "",
                item.direction.value,
                item.dimensions,
            ),
        )
    ):
        raise ValueError(
            "invalid research evidence binding ordering"
        )
    for binding in dossier.evidence_bindings:
        _validate_frozen_evidence(
            binding,
            order=order,
            evidence_as_of=evidence_as_of,
        )

    _validate_company_assessments(
        dossier,
        order=order,
    )
    _validate_findings(
        dossier,
        order=order,
    )

    assessment_by_ticker = {
        item.ticker: item
        for item in dossier.company_assessments
    }
    satisfied = tuple(
        item
        for item in order.requirements
        if _requirement_satisfied(
            item,
            dossier=dossier,
            assessment_by_ticker=assessment_by_ticker,
        )
    )
    satisfied_set = set(satisfied)
    unsatisfied = tuple(
        item
        for item in order.requirements
        if item not in satisfied_set
    )
    if (
        dossier.satisfied_requirements != satisfied
        or dossier.unsatisfied_requirements
        != unsatisfied
    ):
        raise ValueError(
            "inconsistent research requirement partition"
        )

    independent_refs = {
        item.evidence.source_ref
        for item in dossier.evidence_bindings
        if item.independent
    }
    if (
        dossier.independent_source_count
        != len(independent_refs)
    ):
        raise ValueError(
            "inconsistent research independent-source count"
        )

    expected_contradiction = any(
        item.direction
        is ResearchEvidenceDirection.CONTRADICTING
        for item in dossier.evidence_bindings
    ) or any(
        item.kind is not ResearchFindingKind.UNRESOLVED
        and item.direction
        is ResearchEvidenceDirection.CONTRADICTING
        for item in dossier.findings
    )
    expected_unresolved = any(
        item.kind is ResearchFindingKind.UNRESOLVED
        for item in dossier.findings
    )
    if (
        dossier.contradictions_present
        != expected_contradiction
        or dossier.unresolved_present
        != expected_unresolved
        or dossier.status
        is not _expected_dossier_status(
            dossier,
            order=order,
        )
    ):
        raise ValueError(
            "inconsistent research dossier derived state"
        )

    if (
        canonical_hash(
            _dossier_payload_without_hash(dossier)
        )
        != dossier.dossier_hash
    ):
        raise ValueError("research dossier hash mismatch")


def _dossier_archive_payload_without_hash(
    record: ResearchDossierArchiveRecord,
) -> dict[str, object]:
    payload = asdict(record)
    payload.pop("archive_record_hash")
    return payload


def _validate_dossier_archive_record(
    record: ResearchDossierArchiveRecord,
) -> None:
    if (
        record.schema_version != SCHEMA_VERSION
        or record.content_type != DOSSIER_CONTENT_TYPE
        or record.producer != PRODUCER
    ):
        raise ValueError(
            "unsupported research dossier archive contract"
        )
    _validate_work_order_archive_record(
        record.work_order_archive
    )
    for field_name, value in (
        ("research dossier hash", record.dossier_hash),
        (
            "research dossier archive hash",
            record.archive_record_hash,
        ),
    ):
        _validate_sha256(value, field_name=field_name)
    if (
        record.prior_dossier_archive_record_hash
        is not None
    ):
        _validate_sha256(
            record.prior_dossier_archive_record_hash,
            field_name="prior research dossier archive hash",
        )

    if (
        record.source_cycle_as_of
        != record.dossier.source_cycle_as_of
        or record.evidence_as_of
        != record.dossier.evidence_as_of
        or record.dossier_hash
        != record.dossier.dossier_hash
    ):
        raise ValueError(
            "research dossier archive nested identity mismatch"
        )

    order = record.work_order_archive.work_order
    _validate_dossier(
        record.dossier,
        order=order,
    )
    if (
        record.dossier.work_order_hash
        != record.work_order_archive.work_order_hash
        or record.dossier.source_archive_record_hash
        != record.work_order_archive.source_replay_archive_record_hash
        or record.dossier.source_cycle_as_of
        != record.work_order_archive.source_cycle_as_of
        or record.dossier.theme_id != order.theme_id
        or record.dossier.research_mode
        is not order.research_mode
    ):
        raise ValueError(
            "research dossier work-order lineage mismatch"
        )

    if (
        canonical_hash(
            _dossier_archive_payload_without_hash(record)
        )
        != record.archive_record_hash
    ):
        raise ValueError(
            "research dossier archive hash mismatch"
        )


def build_research_dossier_archive_record(
    work_order_archive: ResearchWorkOrderArchiveRecord,
    dossier: ResearchDossier,
    *,
    prior_dossier_archive: ResearchDossierArchiveRecord | None = None,
) -> ResearchDossierArchiveRecord:
    _validate_work_order_archive_record(
        work_order_archive
    )
    _validate_dossier(
        dossier,
        order=work_order_archive.work_order,
    )

    prior_hash = None
    if prior_dossier_archive is not None:
        _validate_dossier_archive_record(
            prior_dossier_archive
        )
        if (
            prior_dossier_archive.work_order_archive
            != work_order_archive
        ):
            raise ValueError(
                "research dossier parent work order mismatch"
            )
        if (
            _parse_utc(dossier.evidence_as_of)
            <= _parse_utc(
                prior_dossier_archive.evidence_as_of
            )
        ):
            raise ValueError(
                "research dossier parent must be strictly earlier"
            )
        prior_hash = (
            prior_dossier_archive.archive_record_hash
        )

    seed = ResearchDossierArchiveRecord(
        schema_version=SCHEMA_VERSION,
        content_type=DOSSIER_CONTENT_TYPE,
        producer=PRODUCER,
        source_cycle_as_of=dossier.source_cycle_as_of,
        evidence_as_of=dossier.evidence_as_of,
        work_order_archive=work_order_archive,
        prior_dossier_archive_record_hash=prior_hash,
        dossier_hash=dossier.dossier_hash,
        dossier=dossier,
        archive_record_hash="0" * 64,
    )
    record = replace(
        seed,
        archive_record_hash=canonical_hash(
            _dossier_archive_payload_without_hash(seed)
        ),
    )
    _validate_dossier_archive_record(record)
    return record


def research_dossier_archive_path(
    record: ResearchDossierArchiveRecord,
    archive_root: str | Path,
) -> Path:
    return (
        Path(archive_root)
        / "dossiers"
        / _cycle_date(record.source_cycle_as_of)
        / record.work_order_archive.work_order_hash
        / f"{record.archive_record_hash}.json"
    )



_WORK_ORDER_POLICY_FIELDS = {
    "version",
    "theme_reassessment_dimensions",
    "industrials_company_dimensions",
    "biotech_company_dimensions",
    "minimum_independent_sources",
    "minimum_independent_sources_per_company",
    "require_usable_linkage_for_company",
}
_RESEARCH_TARGET_FIELDS = {
    "ticker",
    "layer",
    "membership_state",
    "expression_role",
    "effective_from",
    "effective_to",
    "provenance",
}
_RESEARCH_REQUIREMENT_FIELDS = {
    "scope",
    "dimension",
    "target_ticker",
}
_RESEARCH_WORK_ORDER_FIELDS = {
    "schema_version",
    "source_archive_record_hash",
    "source_replay_result_hash",
    "source_cycle_as_of",
    "theme_id",
    "source_routing_intent",
    "source_registered",
    "source_allocated_tier",
    "source_forced_review",
    "authorization",
    "research_mode",
    "evidence_adapter",
    "package_version",
    "universe_version",
    "package_lineage_exactly_recoverable",
    "targets",
    "requirements",
    "minimum_independent_sources",
    "minimum_independent_sources_per_company",
    "contradiction_questions",
    "policy_hash",
    "work_order_hash",
}
_WORK_ORDER_ARCHIVE_FIELDS = {
    "schema_version",
    "content_type",
    "producer",
    "source_cycle_as_of",
    "source_replay_archive_record_hash",
    "source_replay_result_hash",
    "work_order_hash",
    "work_order_policy",
    "work_order",
    "archive_record_hash",
}
_FROZEN_EVIDENCE_FIELDS = {
    "evidence_id",
    "source_hash",
    "payload_hash",
    "observed_at",
    "retrieved_at",
    "market_asof",
    "ticker",
    "theme",
    "source_type",
    "source_ref",
    "fact_type",
    "is_observed_fact",
    "model_version",
    "notes",
}
_EVIDENCE_BINDING_FIELDS = {
    "evidence",
    "independent",
    "direction",
    "dimensions",
    "target_ticker",
}
_NORMALIZED_FIELD_FIELDS = {"name", "value"}
_NORMALIZED_SNAPSHOT_FIELDS = {
    "ticker",
    "as_of",
    "adapter_name",
    "source_coverage",
    "provenance",
    "fields",
    "normalized_payload_hash",
}
_LINKAGE_RESULT_FIELDS = {
    "ticker",
    "control_name",
    "window",
    "correlation",
    "beta",
    "r2",
    "residual_mean",
    "residual_vol",
    "beta_stability",
    "decoupling_score",
    "circularity_warning",
    "observations",
}
_HIERARCHICAL_SNAPSHOT_FIELDS = {
    "target",
    "status",
    "window",
    "observations",
    "theme_correlation",
    "theme_beta",
    "r2",
    "incremental_theme_r2",
    "residual_mean",
    "residual_vol",
    "circularity_warning",
    "missing_controls",
    "coefficients",
    "source_payload_hash",
}
_COMPANY_ASSESSMENT_FIELDS = {
    "ticker",
    "normalized_evidence",
    "evidence_source_hashes",
    "independent_source_count",
    "covered_dimensions",
    "linkage_status",
    "linkage",
    "hierarchical_linkage",
    "cautions",
}
_RESEARCH_FINDING_FIELDS = {
    "finding_id",
    "kind",
    "direction",
    "dimension",
    "target_ticker",
    "statement",
    "evidence_source_hashes",
}
_RESEARCH_DOSSIER_FIELDS = {
    "schema_version",
    "work_order_hash",
    "source_archive_record_hash",
    "source_cycle_as_of",
    "theme_id",
    "research_mode",
    "evidence_as_of",
    "closure",
    "status",
    "evidence_bindings",
    "independent_source_count",
    "satisfied_requirements",
    "unsatisfied_requirements",
    "company_assessments",
    "findings",
    "contradictions_present",
    "unresolved_present",
    "limitations",
    "input_hash",
    "dossier_hash",
}
_DOSSIER_ARCHIVE_FIELDS = {
    "schema_version",
    "content_type",
    "producer",
    "source_cycle_as_of",
    "evidence_as_of",
    "work_order_archive",
    "prior_dossier_archive_record_hash",
    "dossier_hash",
    "dossier",
    "archive_record_hash",
}


def _require_mapping(
    value,
    *,
    label: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a JSON object")
    return value


def _require_exact_fields(
    payload: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{label} fields mismatch: "
            f"missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )


def _require_list(
    value,
    *,
    field_name: str,
) -> list:
    if not isinstance(value, list):
        raise TypeError(
            f"{field_name} must be a JSON array"
        )
    return value


def _require_str(
    value,
    *,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    return value


def _require_optional_str(
    value,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _require_str(
        value,
        field_name=field_name,
    )


def _require_bool(
    value,
    *,
    field_name: str,
) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be bool")
    return value


def _require_int(
    value,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool) or not isinstance(
        value,
        int,
    ):
        raise TypeError(f"{field_name} must be int")
    return value


def _require_number_or_none(
    value,
    *,
    field_name: str,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float),
    ):
        raise TypeError(
            f"{field_name} must be numeric or null"
        )
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    return numeric


def _tuple_of_strings(
    value,
    *,
    field_name: str,
) -> tuple[str, ...]:
    return tuple(
        _require_str(
            item,
            field_name=field_name,
        )
        for item in _require_list(
            value,
            field_name=field_name,
        )
    )


def _reject_json_constant(value: str):
    raise ValueError(
        f"non-finite JSON constant: {value}"
    )


def _decode_work_order_policy(
    value,
) -> ResearchWorkOrderPolicy:
    payload = _require_mapping(
        value,
        label="ResearchWorkOrderPolicy",
    )
    _require_exact_fields(
        payload,
        _WORK_ORDER_POLICY_FIELDS,
        label="ResearchWorkOrderPolicy",
    )
    return ResearchWorkOrderPolicy(
        version=_require_str(
            payload["version"],
            field_name="version",
        ),
        theme_reassessment_dimensions=_tuple_of_strings(
            payload["theme_reassessment_dimensions"],
            field_name="theme_reassessment_dimensions",
        ),
        industrials_company_dimensions=_tuple_of_strings(
            payload["industrials_company_dimensions"],
            field_name="industrials_company_dimensions",
        ),
        biotech_company_dimensions=_tuple_of_strings(
            payload["biotech_company_dimensions"],
            field_name="biotech_company_dimensions",
        ),
        minimum_independent_sources=_require_int(
            payload["minimum_independent_sources"],
            field_name="minimum_independent_sources",
        ),
        minimum_independent_sources_per_company=_require_int(
            payload[
                "minimum_independent_sources_per_company"
            ],
            field_name=(
                "minimum_independent_sources_per_company"
            ),
        ),
        require_usable_linkage_for_company=_require_bool(
            payload["require_usable_linkage_for_company"],
            field_name="require_usable_linkage_for_company",
        ),
    )


def _decode_target(value) -> ResearchTarget:
    payload = _require_mapping(
        value,
        label="ResearchTarget",
    )
    _require_exact_fields(
        payload,
        _RESEARCH_TARGET_FIELDS,
        label="ResearchTarget",
    )
    return ResearchTarget(
        ticker=_require_str(
            payload["ticker"],
            field_name="ticker",
        ),
        layer=_require_str(
            payload["layer"],
            field_name="layer",
        ),
        membership_state=_require_str(
            payload["membership_state"],
            field_name="membership_state",
        ),
        expression_role=_require_str(
            payload["expression_role"],
            field_name="expression_role",
        ),
        effective_from=_require_optional_str(
            payload["effective_from"],
            field_name="effective_from",
        ),
        effective_to=_require_optional_str(
            payload["effective_to"],
            field_name="effective_to",
        ),
        provenance=_tuple_of_strings(
            payload["provenance"],
            field_name="provenance",
        ),
    )


def _decode_requirement(
    value,
) -> ResearchRequirement:
    payload = _require_mapping(
        value,
        label="ResearchRequirement",
    )
    _require_exact_fields(
        payload,
        _RESEARCH_REQUIREMENT_FIELDS,
        label="ResearchRequirement",
    )
    return ResearchRequirement(
        scope=ResearchRequirementScope(
            _require_str(
                payload["scope"],
                field_name="scope",
            )
        ),
        dimension=_require_str(
            payload["dimension"],
            field_name="dimension",
        ),
        target_ticker=_require_optional_str(
            payload["target_ticker"],
            field_name="target_ticker",
        ),
    )


def _decode_work_order(
    value,
) -> ResearchWorkOrder:
    payload = _require_mapping(
        value,
        label="ResearchWorkOrder",
    )
    _require_exact_fields(
        payload,
        _RESEARCH_WORK_ORDER_FIELDS,
        label="ResearchWorkOrder",
    )
    return ResearchWorkOrder(
        schema_version=_require_str(
            payload["schema_version"],
            field_name="schema_version",
        ),
        source_archive_record_hash=_require_str(
            payload["source_archive_record_hash"],
            field_name="source_archive_record_hash",
        ),
        source_replay_result_hash=_require_str(
            payload["source_replay_result_hash"],
            field_name="source_replay_result_hash",
        ),
        source_cycle_as_of=_require_str(
            payload["source_cycle_as_of"],
            field_name="source_cycle_as_of",
        ),
        theme_id=_require_str(
            payload["theme_id"],
            field_name="theme_id",
        ),
        source_routing_intent=RoutingIntent(
            _require_str(
                payload["source_routing_intent"],
                field_name="source_routing_intent",
            )
        ),
        source_registered=_require_bool(
            payload["source_registered"],
            field_name="source_registered",
        ),
        source_allocated_tier=ResearchTier(
            _require_str(
                payload["source_allocated_tier"],
                field_name="source_allocated_tier",
            )
        ),
        source_forced_review=_require_bool(
            payload["source_forced_review"],
            field_name="source_forced_review",
        ),
        authorization=ResearchAuthorization(
            _require_str(
                payload["authorization"],
                field_name="authorization",
            )
        ),
        research_mode=ResearchMode(
            _require_str(
                payload["research_mode"],
                field_name="research_mode",
            )
        ),
        evidence_adapter=_require_optional_str(
            payload["evidence_adapter"],
            field_name="evidence_adapter",
        ),
        package_version=_require_optional_str(
            payload["package_version"],
            field_name="package_version",
        ),
        universe_version=_require_optional_str(
            payload["universe_version"],
            field_name="universe_version",
        ),
        package_lineage_exactly_recoverable=_require_bool(
            payload[
                "package_lineage_exactly_recoverable"
            ],
            field_name=(
                "package_lineage_exactly_recoverable"
            ),
        ),
        targets=tuple(
            _decode_target(item)
            for item in _require_list(
                payload["targets"],
                field_name="targets",
            )
        ),
        requirements=tuple(
            _decode_requirement(item)
            for item in _require_list(
                payload["requirements"],
                field_name="requirements",
            )
        ),
        minimum_independent_sources=_require_int(
            payload["minimum_independent_sources"],
            field_name="minimum_independent_sources",
        ),
        minimum_independent_sources_per_company=_require_int(
            payload[
                "minimum_independent_sources_per_company"
            ],
            field_name=(
                "minimum_independent_sources_per_company"
            ),
        ),
        contradiction_questions=_tuple_of_strings(
            payload["contradiction_questions"],
            field_name="contradiction_questions",
        ),
        policy_hash=_require_str(
            payload["policy_hash"],
            field_name="policy_hash",
        ),
        work_order_hash=_require_str(
            payload["work_order_hash"],
            field_name="work_order_hash",
        ),
    )


def _decode_work_order_archive(
    value,
) -> ResearchWorkOrderArchiveRecord:
    payload = _require_mapping(
        value,
        label="ResearchWorkOrderArchiveRecord",
    )
    _require_exact_fields(
        payload,
        _WORK_ORDER_ARCHIVE_FIELDS,
        label="ResearchWorkOrderArchiveRecord",
    )
    record = ResearchWorkOrderArchiveRecord(
        schema_version=_require_str(
            payload["schema_version"],
            field_name="schema_version",
        ),
        content_type=_require_str(
            payload["content_type"],
            field_name="content_type",
        ),
        producer=_require_str(
            payload["producer"],
            field_name="producer",
        ),
        source_cycle_as_of=_require_str(
            payload["source_cycle_as_of"],
            field_name="source_cycle_as_of",
        ),
        source_replay_archive_record_hash=_require_str(
            payload[
                "source_replay_archive_record_hash"
            ],
            field_name=(
                "source_replay_archive_record_hash"
            ),
        ),
        source_replay_result_hash=_require_str(
            payload["source_replay_result_hash"],
            field_name="source_replay_result_hash",
        ),
        work_order_hash=_require_str(
            payload["work_order_hash"],
            field_name="work_order_hash",
        ),
        work_order_policy=_decode_work_order_policy(
            payload["work_order_policy"]
        ),
        work_order=_decode_work_order(
            payload["work_order"]
        ),
        archive_record_hash=_require_str(
            payload["archive_record_hash"],
            field_name="archive_record_hash",
        ),
    )
    _validate_work_order_archive_record(record)
    return record


def _decode_frozen_evidence(
    value,
) -> FrozenResearchEvidence:
    payload = _require_mapping(
        value,
        label="FrozenResearchEvidence",
    )
    _require_exact_fields(
        payload,
        _FROZEN_EVIDENCE_FIELDS,
        label="FrozenResearchEvidence",
    )
    return FrozenResearchEvidence(
        evidence_id=_require_str(
            payload["evidence_id"],
            field_name="evidence_id",
        ),
        source_hash=_require_str(
            payload["source_hash"],
            field_name="source_hash",
        ),
        payload_hash=_require_str(
            payload["payload_hash"],
            field_name="payload_hash",
        ),
        observed_at=_require_str(
            payload["observed_at"],
            field_name="observed_at",
        ),
        retrieved_at=_require_optional_str(
            payload["retrieved_at"],
            field_name="retrieved_at",
        ),
        market_asof=_require_optional_str(
            payload["market_asof"],
            field_name="market_asof",
        ),
        ticker=_require_optional_str(
            payload["ticker"],
            field_name="ticker",
        ),
        theme=_require_optional_str(
            payload["theme"],
            field_name="theme",
        ),
        source_type=_require_str(
            payload["source_type"],
            field_name="source_type",
        ),
        source_ref=_require_str(
            payload["source_ref"],
            field_name="source_ref",
        ),
        fact_type=_require_str(
            payload["fact_type"],
            field_name="fact_type",
        ),
        is_observed_fact=_require_bool(
            payload["is_observed_fact"],
            field_name="is_observed_fact",
        ),
        model_version=_require_optional_str(
            payload["model_version"],
            field_name="model_version",
        ),
        notes=_require_optional_str(
            payload["notes"],
            field_name="notes",
        ),
    )


def _decode_evidence_binding(
    value,
) -> ResearchEvidenceBinding:
    payload = _require_mapping(
        value,
        label="ResearchEvidenceBinding",
    )
    _require_exact_fields(
        payload,
        _EVIDENCE_BINDING_FIELDS,
        label="ResearchEvidenceBinding",
    )
    return ResearchEvidenceBinding(
        evidence=_decode_frozen_evidence(
            payload["evidence"]
        ),
        independent=_require_bool(
            payload["independent"],
            field_name="independent",
        ),
        direction=ResearchEvidenceDirection(
            _require_str(
                payload["direction"],
                field_name="direction",
            )
        ),
        dimensions=_tuple_of_strings(
            payload["dimensions"],
            field_name="dimensions",
        ),
        target_ticker=_require_optional_str(
            payload["target_ticker"],
            field_name="target_ticker",
        ),
    )


def _decode_normalized_field(
    value,
) -> NormalizedCompanyField:
    payload = _require_mapping(
        value,
        label="NormalizedCompanyField",
    )
    _require_exact_fields(
        payload,
        _NORMALIZED_FIELD_FIELDS,
        label="NormalizedCompanyField",
    )
    raw = payload["value"]
    if isinstance(raw, bool) or not isinstance(
        raw,
        (int, float, str),
    ):
        raise TypeError(
            "normalized company field value has invalid type"
        )
    if (
        isinstance(raw, float)
        and not isfinite(raw)
    ):
        raise ValueError(
            "normalized company field value must be finite"
        )
    return NormalizedCompanyField(
        name=_require_str(
            payload["name"],
            field_name="name",
        ),
        value=raw,
    )


def _decode_normalized_snapshot(
    value,
) -> NormalizedCompanySnapshot:
    payload = _require_mapping(
        value,
        label="NormalizedCompanySnapshot",
    )
    _require_exact_fields(
        payload,
        _NORMALIZED_SNAPSHOT_FIELDS,
        label="NormalizedCompanySnapshot",
    )
    return NormalizedCompanySnapshot(
        ticker=_require_str(
            payload["ticker"],
            field_name="ticker",
        ),
        as_of=_require_str(
            payload["as_of"],
            field_name="as_of",
        ),
        adapter_name=_require_str(
            payload["adapter_name"],
            field_name="adapter_name",
        ),
        source_coverage=_require_str(
            payload["source_coverage"],
            field_name="source_coverage",
        ),
        provenance=_tuple_of_strings(
            payload["provenance"],
            field_name="provenance",
        ),
        fields=tuple(
            _decode_normalized_field(item)
            for item in _require_list(
                payload["fields"],
                field_name="fields",
            )
        ),
        normalized_payload_hash=_require_str(
            payload["normalized_payload_hash"],
            field_name="normalized_payload_hash",
        ),
    )


def _decode_linkage_result(
    value,
) -> LinkageResult:
    payload = _require_mapping(
        value,
        label="LinkageResult",
    )
    _require_exact_fields(
        payload,
        _LINKAGE_RESULT_FIELDS,
        label="LinkageResult",
    )
    return LinkageResult(
        ticker=_require_str(
            payload["ticker"],
            field_name="ticker",
        ),
        control_name=_require_str(
            payload["control_name"],
            field_name="control_name",
        ),
        window=_require_int(
            payload["window"],
            field_name="window",
        ),
        correlation=_require_number_or_none(
            payload["correlation"],
            field_name="correlation",
        ),
        beta=_require_number_or_none(
            payload["beta"],
            field_name="beta",
        ),
        r2=_require_number_or_none(
            payload["r2"],
            field_name="r2",
        ),
        residual_mean=_require_number_or_none(
            payload["residual_mean"],
            field_name="residual_mean",
        ),
        residual_vol=_require_number_or_none(
            payload["residual_vol"],
            field_name="residual_vol",
        ),
        beta_stability=_require_number_or_none(
            payload["beta_stability"],
            field_name="beta_stability",
        ),
        decoupling_score=_require_number_or_none(
            payload["decoupling_score"],
            field_name="decoupling_score",
        ),
        circularity_warning=_require_bool(
            payload["circularity_warning"],
            field_name="circularity_warning",
        ),
        observations=_require_int(
            payload["observations"],
            field_name="observations",
        ),
    )


def _decode_hierarchical_snapshot(
    value,
) -> HierarchicalLinkageSnapshot:
    payload = _require_mapping(
        value,
        label="HierarchicalLinkageSnapshot",
    )
    _require_exact_fields(
        payload,
        _HIERARCHICAL_SNAPSHOT_FIELDS,
        label="HierarchicalLinkageSnapshot",
    )
    coefficients: list[tuple[str, float]] = []
    for item in _require_list(
        payload["coefficients"],
        field_name="coefficients",
    ):
        if not isinstance(item, list) or len(item) != 2:
            raise TypeError(
                "coefficient must be a two-item JSON array"
            )
        name = _require_str(
            item[0],
            field_name="coefficient name",
        )
        number = _require_number_or_none(
            item[1],
            field_name="coefficient value",
        )
        if number is None:
            raise TypeError(
                "coefficient value must be numeric"
            )
        coefficients.append((name, number))
    return HierarchicalLinkageSnapshot(
        target=_require_str(
            payload["target"],
            field_name="target",
        ),
        status=_require_str(
            payload["status"],
            field_name="status",
        ),
        window=_require_int(
            payload["window"],
            field_name="window",
        ),
        observations=_require_int(
            payload["observations"],
            field_name="observations",
        ),
        theme_correlation=_require_number_or_none(
            payload["theme_correlation"],
            field_name="theme_correlation",
        ),
        theme_beta=_require_number_or_none(
            payload["theme_beta"],
            field_name="theme_beta",
        ),
        r2=_require_number_or_none(
            payload["r2"],
            field_name="r2",
        ),
        incremental_theme_r2=_require_number_or_none(
            payload["incremental_theme_r2"],
            field_name="incremental_theme_r2",
        ),
        residual_mean=_require_number_or_none(
            payload["residual_mean"],
            field_name="residual_mean",
        ),
        residual_vol=_require_number_or_none(
            payload["residual_vol"],
            field_name="residual_vol",
        ),
        circularity_warning=_require_bool(
            payload["circularity_warning"],
            field_name="circularity_warning",
        ),
        missing_controls=_tuple_of_strings(
            payload["missing_controls"],
            field_name="missing_controls",
        ),
        coefficients=tuple(coefficients),
        source_payload_hash=_require_str(
            payload["source_payload_hash"],
            field_name="source_payload_hash",
        ),
    )


def _decode_company_assessment(
    value,
) -> CompanyResearchAssessment:
    payload = _require_mapping(
        value,
        label="CompanyResearchAssessment",
    )
    _require_exact_fields(
        payload,
        _COMPANY_ASSESSMENT_FIELDS,
        label="CompanyResearchAssessment",
    )
    normalized = payload["normalized_evidence"]
    simple = payload["linkage"]
    hierarchical = payload["hierarchical_linkage"]
    return CompanyResearchAssessment(
        ticker=_require_str(
            payload["ticker"],
            field_name="ticker",
        ),
        normalized_evidence=(
            None
            if normalized is None
            else _decode_normalized_snapshot(
                normalized
            )
        ),
        evidence_source_hashes=_tuple_of_strings(
            payload["evidence_source_hashes"],
            field_name="evidence_source_hashes",
        ),
        independent_source_count=_require_int(
            payload["independent_source_count"],
            field_name="independent_source_count",
        ),
        covered_dimensions=_tuple_of_strings(
            payload["covered_dimensions"],
            field_name="covered_dimensions",
        ),
        linkage_status=CompanyLinkageStatus(
            _require_str(
                payload["linkage_status"],
                field_name="linkage_status",
            )
        ),
        linkage=(
            None
            if simple is None
            else _decode_linkage_result(simple)
        ),
        hierarchical_linkage=(
            None
            if hierarchical is None
            else _decode_hierarchical_snapshot(
                hierarchical
            )
        ),
        cautions=_tuple_of_strings(
            payload["cautions"],
            field_name="cautions",
        ),
    )


def _decode_finding(
    value,
) -> ResearchFinding:
    payload = _require_mapping(
        value,
        label="ResearchFinding",
    )
    _require_exact_fields(
        payload,
        _RESEARCH_FINDING_FIELDS,
        label="ResearchFinding",
    )
    direction = payload["direction"]
    return ResearchFinding(
        finding_id=_require_str(
            payload["finding_id"],
            field_name="finding_id",
        ),
        kind=ResearchFindingKind(
            _require_str(
                payload["kind"],
                field_name="kind",
            )
        ),
        direction=(
            None
            if direction is None
            else ResearchEvidenceDirection(
                _require_str(
                    direction,
                    field_name="direction",
                )
            )
        ),
        dimension=_require_str(
            payload["dimension"],
            field_name="dimension",
        ),
        target_ticker=_require_optional_str(
            payload["target_ticker"],
            field_name="target_ticker",
        ),
        statement=_require_str(
            payload["statement"],
            field_name="statement",
        ),
        evidence_source_hashes=_tuple_of_strings(
            payload["evidence_source_hashes"],
            field_name="evidence_source_hashes",
        ),
    )


def _decode_dossier(
    value,
) -> ResearchDossier:
    payload = _require_mapping(
        value,
        label="ResearchDossier",
    )
    _require_exact_fields(
        payload,
        _RESEARCH_DOSSIER_FIELDS,
        label="ResearchDossier",
    )
    return ResearchDossier(
        schema_version=_require_str(
            payload["schema_version"],
            field_name="schema_version",
        ),
        work_order_hash=_require_str(
            payload["work_order_hash"],
            field_name="work_order_hash",
        ),
        source_archive_record_hash=_require_str(
            payload["source_archive_record_hash"],
            field_name="source_archive_record_hash",
        ),
        source_cycle_as_of=_require_str(
            payload["source_cycle_as_of"],
            field_name="source_cycle_as_of",
        ),
        theme_id=_require_str(
            payload["theme_id"],
            field_name="theme_id",
        ),
        research_mode=ResearchMode(
            _require_str(
                payload["research_mode"],
                field_name="research_mode",
            )
        ),
        evidence_as_of=_require_str(
            payload["evidence_as_of"],
            field_name="evidence_as_of",
        ),
        closure=ResearchExecutionClosure(
            _require_str(
                payload["closure"],
                field_name="closure",
            )
        ),
        status=ResearchDossierStatus(
            _require_str(
                payload["status"],
                field_name="status",
            )
        ),
        evidence_bindings=tuple(
            _decode_evidence_binding(item)
            for item in _require_list(
                payload["evidence_bindings"],
                field_name="evidence_bindings",
            )
        ),
        independent_source_count=_require_int(
            payload["independent_source_count"],
            field_name="independent_source_count",
        ),
        satisfied_requirements=tuple(
            _decode_requirement(item)
            for item in _require_list(
                payload["satisfied_requirements"],
                field_name="satisfied_requirements",
            )
        ),
        unsatisfied_requirements=tuple(
            _decode_requirement(item)
            for item in _require_list(
                payload["unsatisfied_requirements"],
                field_name="unsatisfied_requirements",
            )
        ),
        company_assessments=tuple(
            _decode_company_assessment(item)
            for item in _require_list(
                payload["company_assessments"],
                field_name="company_assessments",
            )
        ),
        findings=tuple(
            _decode_finding(item)
            for item in _require_list(
                payload["findings"],
                field_name="findings",
            )
        ),
        contradictions_present=_require_bool(
            payload["contradictions_present"],
            field_name="contradictions_present",
        ),
        unresolved_present=_require_bool(
            payload["unresolved_present"],
            field_name="unresolved_present",
        ),
        limitations=_tuple_of_strings(
            payload["limitations"],
            field_name="limitations",
        ),
        input_hash=_require_str(
            payload["input_hash"],
            field_name="input_hash",
        ),
        dossier_hash=_require_str(
            payload["dossier_hash"],
            field_name="dossier_hash",
        ),
    )


def _decode_dossier_archive(
    value,
) -> ResearchDossierArchiveRecord:
    payload = _require_mapping(
        value,
        label="ResearchDossierArchiveRecord",
    )
    _require_exact_fields(
        payload,
        _DOSSIER_ARCHIVE_FIELDS,
        label="ResearchDossierArchiveRecord",
    )
    record = ResearchDossierArchiveRecord(
        schema_version=_require_str(
            payload["schema_version"],
            field_name="schema_version",
        ),
        content_type=_require_str(
            payload["content_type"],
            field_name="content_type",
        ),
        producer=_require_str(
            payload["producer"],
            field_name="producer",
        ),
        source_cycle_as_of=_require_str(
            payload["source_cycle_as_of"],
            field_name="source_cycle_as_of",
        ),
        evidence_as_of=_require_str(
            payload["evidence_as_of"],
            field_name="evidence_as_of",
        ),
        work_order_archive=_decode_work_order_archive(
            payload["work_order_archive"]
        ),
        prior_dossier_archive_record_hash=_require_optional_str(
            payload[
                "prior_dossier_archive_record_hash"
            ],
            field_name=(
                "prior_dossier_archive_record_hash"
            ),
        ),
        dossier_hash=_require_str(
            payload["dossier_hash"],
            field_name="dossier_hash",
        ),
        dossier=_decode_dossier(
            payload["dossier"]
        ),
        archive_record_hash=_require_str(
            payload["archive_record_hash"],
            field_name="archive_record_hash",
        ),
    )
    _validate_dossier_archive_record(record)
    return record


def _load_json(path: Path):
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_json_constant,
    )


def read_research_work_order_archive(
    path: str | Path,
) -> ResearchWorkOrderArchiveRecord:
    target = Path(path)
    record = _decode_work_order_archive(
        _load_json(target)
    )
    if (
        target.name
        != f"{record.work_order_hash}.json"
    ):
        raise ValueError(
            "research work-order archive filename mismatch"
        )
    if (
        target.parent.name
        != _cycle_date(record.source_cycle_as_of)
    ):
        raise ValueError(
            "research archive cycle directory mismatch"
        )
    return record


def read_research_dossier_archive(
    path: str | Path,
) -> ResearchDossierArchiveRecord:
    target = Path(path)
    record = _decode_dossier_archive(
        _load_json(target)
    )
    if (
        target.name
        != f"{record.archive_record_hash}.json"
    ):
        raise ValueError(
            "research dossier archive filename mismatch"
        )
    if (
        target.parent.name
        != record.work_order_archive.work_order_hash
    ):
        raise ValueError(
            "research dossier work-order directory mismatch"
        )
    if (
        target.parent.parent.name
        != _cycle_date(record.source_cycle_as_of)
    ):
        raise ValueError(
            "research archive cycle directory mismatch"
        )
    return record


def verify_research_work_order_archive(
    path: str | Path,
) -> bool:
    try:
        read_research_work_order_archive(path)
    except FileNotFoundError:
        return False
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return False
    return True


def verify_research_dossier_archive(
    path: str | Path,
) -> bool:
    try:
        read_research_dossier_archive(path)
    except FileNotFoundError:
        return False
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return False
    return True



def _record_payload(record) -> dict[str, object]:
    return asdict(record)


def _serialize_record(record) -> bytes:
    return (
        json.dumps(
            _record_payload(record),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _contains_path_sequence(
    parts: tuple[str, ...],
    sequence: tuple[str, ...],
) -> bool:
    width = len(sequence)
    return any(
        tuple(parts[index : index + width])
        == sequence
        for index in range(
            len(parts) - width + 1
        )
    )


def _validate_destination_policy(
    archive_root: str | Path,
    *,
    destination_visibility: ResearchArchiveDestinationVisibility,
    public_safe: bool,
) -> Path:
    if not isinstance(
        destination_visibility,
        ResearchArchiveDestinationVisibility,
    ):
        raise TypeError(
            "invalid research archive destination visibility"
        )

    resolved = (
        Path(archive_root)
        .expanduser()
        .resolve(strict=False)
    )
    parts = tuple(resolved.parts)
    if _contains_path_sequence(
        parts,
        ("ledger", "live"),
    ):
        raise ValueError(
            "research archives may not be written under ledger/live"
        )

    if (
        destination_visibility
        is ResearchArchiveDestinationVisibility.PUBLIC
    ):
        if public_safe is not True:
            raise PermissionError(
                "public research archive write requires explicit public_safe=True"
            )
        if (
            len(parts) < 2
            or parts[-2:]
            != (
                "recomputed",
                "research_execution",
            )
        ):
            raise ValueError(
                "public research archives must use recomputed/research_execution"
            )
    return resolved


def _ensure_parent_within_root(
    path: Path,
    root: Path,
) -> None:
    resolved_parent = path.parent.resolve(
        strict=False
    )
    if not resolved_parent.is_relative_to(root):
        raise ValueError(
            "research archive directory escapes archive root"
        )


def _write_archive_record(
    record,
    path: Path,
    root: Path,
    *,
    reader,
    content_hash: str,
) -> ResearchArchiveWriteResult:
    requested_payload = _record_payload(record)
    requested_bytes = _serialize_record(record)

    _ensure_parent_within_root(path, root)
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    _ensure_parent_within_root(path, root)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(
            path,
            flags,
            0o644,
        )
    except FileExistsError:
        if path.is_symlink() or path.is_dir():
            raise FileExistsError(
                "research archive path conflict"
            ) from None
        try:
            existing = reader(path)
        except (
            FileNotFoundError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise FileExistsError(
                "research archive path conflict"
            ) from exc
        if (
            _record_payload(existing)
            != requested_payload
        ):
            raise FileExistsError(
                "research archive path conflict"
            )
        return ResearchArchiveWriteResult(
            path=path,
            created=False,
            content_hash=content_hash,
            archive_record_hash=(
                record.archive_record_hash
            ),
        )

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(requested_bytes)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    return ResearchArchiveWriteResult(
        path=path,
        created=True,
        content_hash=content_hash,
        archive_record_hash=(
            record.archive_record_hash
        ),
    )


def write_research_work_order_archive(
    record: ResearchWorkOrderArchiveRecord,
    archive_root: str | Path,
    *,
    destination_visibility: ResearchArchiveDestinationVisibility,
    public_safe: bool = False,
) -> ResearchArchiveWriteResult:
    root = _validate_destination_policy(
        archive_root,
        destination_visibility=destination_visibility,
        public_safe=public_safe,
    )
    _validate_work_order_archive_record(record)
    path = research_work_order_archive_path(
        record,
        root,
    )
    return _write_archive_record(
        record,
        path,
        root,
        reader=read_research_work_order_archive,
        content_hash=record.work_order_hash,
    )


def write_research_dossier_archive(
    record: ResearchDossierArchiveRecord,
    archive_root: str | Path,
    *,
    destination_visibility: ResearchArchiveDestinationVisibility,
    public_safe: bool = False,
) -> ResearchArchiveWriteResult:
    root = _validate_destination_policy(
        archive_root,
        destination_visibility=destination_visibility,
        public_safe=public_safe,
    )
    _validate_dossier_archive_record(record)
    path = research_dossier_archive_path(
        record,
        root,
    )
    return _write_archive_record(
        record,
        path,
        root,
        reader=read_research_dossier_archive,
        content_hash=record.dossier_hash,
    )
