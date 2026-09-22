from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from math import isfinite
from pathlib import Path

from .evidence import SOURCE_PRIORITY
from .hierarchical import HierarchicalLinkageResult
from .ledger import canonical_hash
from .linkage import LinkageResult
from .replay_archive import ReplayArchiveRecord, build_replay_archive_record
from .replay_cohort import evaluate_replay_cohort
from .research_execution import (
    CompanyLinkageStatus,
    CompanyResearchAssessment,
    HierarchicalLinkageSnapshot,
    ResearchDossier,
    ResearchDossierStatus,
    ResearchEvidenceBinding,
    ResearchEvidenceDirection,
    ResearchExecutionClosure,
    ResearchFindingKind,
    ResearchMode,
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
