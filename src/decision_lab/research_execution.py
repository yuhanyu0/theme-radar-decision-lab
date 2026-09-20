from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from enum import Enum
from math import isfinite

from .adapters import (
    BiotechClinicalAdapter,
    BiotechClinicalEvidence,
    CompanyEvidenceInput,
    IndustrialsInfrastructureAdapter,
    NormalizedCompanyEvidence,
    RawFactValue,
)
from .evidence import EvidenceRecord
from .hierarchical import HierarchicalLinkageResult
from .ledger import canonical_hash
from .linkage import LinkageResult
from .replay_archive import ReplayArchiveRecord
from .replay_cohort import RoutingIntent, evaluate_replay_cohort
from .research_budget import ResearchTier
from .themes import ThemePackage

SCHEMA_VERSION = "0.1"


class ResearchMode(str, Enum):
    THEME_REASSESSMENT = "THEME_REASSESSMENT"
    COMPANY_DEEP_DIVE = "COMPANY_DEEP_DIVE"


class ResearchAuthorization(str, Enum):
    ALLOCATED_FULL = "ALLOCATED_FULL"
    UNREGISTERED_FORCED_REVIEW = "UNREGISTERED_FORCED_REVIEW"


class ResearchRequirementScope(str, Enum):
    THEME_EVIDENCE = "THEME_EVIDENCE"
    COMPANY_EVIDENCE = "COMPANY_EVIDENCE"
    COMPANY_LINKAGE = "COMPANY_LINKAGE"


@dataclass(frozen=True)
class ResearchRequirement:
    scope: ResearchRequirementScope
    dimension: str
    target_ticker: str | None


@dataclass(frozen=True)
class ResearchTarget:
    ticker: str
    layer: str
    membership_state: str
    expression_role: str
    effective_from: str | None
    effective_to: str | None
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class ResearchWorkOrderPolicy:
    version: str = "0.1"
    theme_reassessment_dimensions: tuple[str, ...] = (
        "theme_structure",
        "independent_support",
        "independent_contradiction",
        "universe_integrity",
    )
    industrials_company_dimensions: tuple[str, ...] = (
        "growth",
        "margin_quality",
        "demand_visibility",
        "order_or_contract_visibility",
        "capital_intensity",
        "cash_generation",
        "balance_sheet_strength",
        "customer_concentration",
        "guidance_revision",
        "thesis_risk",
    )
    biotech_company_dimensions: tuple[str, ...] = (
        "clinical_phase",
        "endpoint_status",
        "regulatory_state",
        "cash_runway_months",
        "days_to_material_catalyst",
        "financing_risk",
        "platform_validation",
        "partnered_economics",
    )
    minimum_independent_sources: int = 2
    minimum_independent_sources_per_company: int = 1
    require_usable_linkage_for_company: bool = True


@dataclass(frozen=True)
class ResearchWorkOrder:
    schema_version: str
    source_archive_record_hash: str
    source_replay_result_hash: str
    source_cycle_as_of: str
    theme_id: str
    source_routing_intent: RoutingIntent
    source_registered: bool
    source_allocated_tier: ResearchTier
    source_forced_review: bool
    authorization: ResearchAuthorization
    research_mode: ResearchMode
    evidence_adapter: str | None
    package_version: str | None
    universe_version: str | None
    package_lineage_exactly_recoverable: bool
    targets: tuple[ResearchTarget, ...]
    requirements: tuple[ResearchRequirement, ...]
    minimum_independent_sources: int
    minimum_independent_sources_per_company: int
    contradiction_questions: tuple[str, ...]
    policy_hash: str
    work_order_hash: str


_CONTRADICTION_QUESTIONS = (
    "What independent evidence contradicts the current theme thesis?",
    "Is the contradiction persistent, structural, or coverage-related?",
    "What evidence would resolve rather than merely remove the contradiction?",
)


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


def _normalize_dimensions(
    values: Sequence[str],
    *,
    field_name: str,
) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError(f"{field_name} contains blank dimension")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} contains duplicate dimension")
    return tuple(sorted(normalized))


def _normalize_policy(
    policy: ResearchWorkOrderPolicy,
) -> ResearchWorkOrderPolicy:
    for name in (
        "minimum_independent_sources",
        "minimum_independent_sources_per_company",
    ):
        value = getattr(policy, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if not isinstance(policy.require_usable_linkage_for_company, bool):
        raise TypeError("require_usable_linkage_for_company must be bool")
    if not policy.version.strip():
        raise ValueError("research policy version must be non-empty")
    return replace(
        policy,
        version=policy.version.strip(),
        theme_reassessment_dimensions=_normalize_dimensions(
            policy.theme_reassessment_dimensions,
            field_name="theme_reassessment_dimensions",
        ),
        industrials_company_dimensions=_normalize_dimensions(
            policy.industrials_company_dimensions,
            field_name="industrials_company_dimensions",
        ),
        biotech_company_dimensions=_normalize_dimensions(
            policy.biotech_company_dimensions,
            field_name="biotech_company_dimensions",
        ),
    )


def _source_transition(
    record: ReplayArchiveRecord,
    theme_id: str,
):
    cohort = evaluate_replay_cohort((record,), horizons=(1,))
    matches = [
        item
        for item in cohort.transitions
        if item.theme_id == theme_id
    ]
    if len(matches) != 1:
        raise ValueError("theme missing from source replay")
    return matches[0]


def _effective_cycle_date(value: str) -> str:
    return _parse_utc(value).date().isoformat()


def _validate_package_lineage(
    record: ReplayArchiveRecord,
    theme_id: str,
    package: ThemePackage,
) -> tuple[str, str]:
    if (
        package.definition.theme_id != theme_id
        or package.universe.theme != theme_id
    ):
        raise ValueError("research package theme mismatch")

    cycle_date = _effective_cycle_date(record.cycle_as_of)
    definition = package.definition
    if (
        definition.effective_from is not None
        and cycle_date < definition.effective_from
    ) or (
        definition.effective_to is not None
        and cycle_date >= definition.effective_to
    ):
        raise ValueError("research package is not effective at source cycle")

    source_theme = next(
        (
            item
            for item in record.replay_result.theme_records
            if item.theme_id == theme_id
        ),
        None,
    )
    if source_theme is None or source_theme.market_batch is None:
        raise ValueError("source replay package lineage is inconsistent")

    package_versions = {
        item.package_version
        for item in source_theme.market_batch.diagnostics
    }
    universe_versions = {
        item.universe_version
        for item in source_theme.market_batch.diagnostics
    }
    if (
        len(package_versions) != 1
        or len(universe_versions) != 1
        or "" in package_versions
        or "" in universe_versions
    ):
        raise ValueError("source replay package lineage is inconsistent")

    replay_package_version = next(iter(package_versions))
    replay_universe_version = next(iter(universe_versions))
    if (
        replay_package_version != package.version
        or replay_universe_version != package.universe.version
    ):
        raise ValueError("source replay package lineage is inconsistent")
    return replay_package_version, replay_universe_version


def _company_dimensions(
    adapter_name: str,
    policy: ResearchWorkOrderPolicy,
) -> tuple[str, ...]:
    if adapter_name == "generic":
        raise ValueError(
            "generic adapter is not eligible for company deep dive"
        )
    if adapter_name == "industrials_infrastructure":
        dimensions = policy.industrials_company_dimensions
        allowed = {
            field.name for field in fields(NormalizedCompanyEvidence)
        }
    elif adapter_name == "biotech_clinical":
        dimensions = policy.biotech_company_dimensions
        allowed = {
            field.name for field in fields(BiotechClinicalEvidence)
        }
    else:
        raise ValueError("unsupported company evidence adapter")

    allowed -= {
        "ticker",
        "as_of",
        "source_coverage",
        "provenance",
        "raw_facts",
    }
    if any(dimension not in allowed for dimension in dimensions):
        raise ValueError(
            "company requirement dimension is unsupported by adapter"
        )
    return dimensions


def _build_targets(
    package: ThemePackage,
    cycle_date: str,
    target_tickers: Sequence[str],
) -> tuple[ResearchTarget, ...]:
    normalized = tuple(ticker.strip().upper() for ticker in target_tickers)
    if not normalized:
        raise ValueError("company deep dive requires target tickers")
    if any(not ticker for ticker in normalized):
        raise ValueError("company target ticker must be non-empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate company target ticker")

    active = {
        item.ticker.upper(): item
        for item in package.universe.active_candidates(as_of=cycle_date)
    }
    if any(ticker not in active for ticker in normalized):
        raise ValueError("company target is not effective in source universe")

    return tuple(
        ResearchTarget(
            ticker=ticker,
            layer=active[ticker].layer,
            membership_state=active[ticker].membership_state,
            expression_role=active[ticker].expression_role,
            effective_from=active[ticker].effective_from,
            effective_to=active[ticker].effective_to,
            provenance=tuple(active[ticker].provenance),
        )
        for ticker in sorted(normalized)
    )


def _build_requirements(
    *,
    mode: ResearchMode,
    targets: tuple[ResearchTarget, ...],
    adapter_name: str | None,
    policy: ResearchWorkOrderPolicy,
) -> tuple[ResearchRequirement, ...]:
    rows: list[ResearchRequirement] = []
    if mode is ResearchMode.THEME_REASSESSMENT:
        rows.extend(
            ResearchRequirement(
                scope=ResearchRequirementScope.THEME_EVIDENCE,
                dimension=dimension,
                target_ticker=None,
            )
            for dimension in policy.theme_reassessment_dimensions
        )
    else:
        assert adapter_name is not None
        dimensions = _company_dimensions(adapter_name, policy)
        for target in targets:
            rows.extend(
                ResearchRequirement(
                    scope=ResearchRequirementScope.COMPANY_EVIDENCE,
                    dimension=dimension,
                    target_ticker=target.ticker,
                )
                for dimension in dimensions
            )
            if policy.require_usable_linkage_for_company:
                rows.append(
                    ResearchRequirement(
                        scope=ResearchRequirementScope.COMPANY_LINKAGE,
                        dimension="theme_linkage",
                        target_ticker=target.ticker,
                    )
                )
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                item.scope.value,
                item.target_ticker or "",
                item.dimension,
            ),
        )
    )


def _work_order_payload_without_hash(
    order: ResearchWorkOrder,
) -> dict[str, object]:
    payload = asdict(order)
    payload.pop("work_order_hash")
    return payload


def _validate_work_order_semantics(order: ResearchWorkOrder) -> None:
    invalid = ValueError("invalid research work order")
    if (
        order.schema_version != SCHEMA_VERSION
        or not order.theme_id.strip()
        or order.package_lineage_exactly_recoverable is not False
        or isinstance(order.minimum_independent_sources, bool)
        or not isinstance(order.minimum_independent_sources, int)
        or order.minimum_independent_sources < 0
        or isinstance(order.minimum_independent_sources_per_company, bool)
        or not isinstance(order.minimum_independent_sources_per_company, int)
        or order.minimum_independent_sources_per_company < 0
    ):
        raise invalid

    if order.source_routing_intent is RoutingIntent.ORDINARY_FULL_RESEARCH:
        if (
            not order.source_registered
            or order.source_allocated_tier is not ResearchTier.FULL_DECISION_RESEARCH
            or order.source_forced_review
            or order.authorization is not ResearchAuthorization.ALLOCATED_FULL
            or order.research_mode is not ResearchMode.COMPANY_DEEP_DIVE
        ):
            raise invalid
    elif order.source_routing_intent is RoutingIntent.FORCED_FULL_REVIEW:
        if (
            not order.source_registered
            or order.source_allocated_tier is not ResearchTier.FULL_DECISION_RESEARCH
            or not order.source_forced_review
            or order.authorization is not ResearchAuthorization.ALLOCATED_FULL
        ):
            raise invalid
    elif order.source_routing_intent is RoutingIntent.FORCED_REVIEW_UNREGISTERED:
        if (
            order.source_registered
            or order.source_allocated_tier is not ResearchTier.SCAN_ONLY
            or not order.source_forced_review
            or order.authorization
            is not ResearchAuthorization.UNREGISTERED_FORCED_REVIEW
            or order.research_mode is not ResearchMode.THEME_REASSESSMENT
        ):
            raise invalid
    else:
        raise invalid

    if order.source_registered:
        if (
            order.evidence_adapter is None
            or order.package_version is None
            or order.universe_version is None
        ):
            raise invalid
    elif (
        order.evidence_adapter is not None
        or order.package_version is not None
        or order.universe_version is not None
    ):
        raise invalid

    target_ids = {target.ticker for target in order.targets}
    if len(target_ids) != len(order.targets):
        raise invalid

    if order.research_mode is ResearchMode.THEME_REASSESSMENT:
        if order.targets:
            raise invalid
        if any(
            requirement.scope is not ResearchRequirementScope.THEME_EVIDENCE
            or requirement.target_ticker is not None
            for requirement in order.requirements
        ):
            raise invalid
    elif order.research_mode is ResearchMode.COMPANY_DEEP_DIVE:
        if (
            not order.targets
            or order.evidence_adapter in (None, "generic")
            or any(
                requirement.scope is ResearchRequirementScope.THEME_EVIDENCE
                or requirement.target_ticker not in target_ids
                for requirement in order.requirements
            )
        ):
            raise invalid
    else:
        raise invalid

    if order.source_forced_review:
        if not order.contradiction_questions:
            raise invalid
    elif order.contradiction_questions:
        raise invalid


def _validate_work_order_hash(order: ResearchWorkOrder) -> None:
    if (
        canonical_hash(_work_order_payload_without_hash(order))
        != order.work_order_hash
    ):
        raise ValueError("invalid research work order")
    _validate_work_order_semantics(order)


def build_research_work_order(
    source_record: ReplayArchiveRecord,
    theme_id: str,
    research_mode: ResearchMode,
    *,
    theme_package: ThemePackage | None = None,
    target_tickers: Sequence[str] = (),
    policy: ResearchWorkOrderPolicy = ResearchWorkOrderPolicy(),
) -> ResearchWorkOrder:
    if not isinstance(research_mode, ResearchMode):
        raise TypeError("unsupported research mode")
    theme_id = theme_id.strip()
    if not theme_id:
        raise ValueError("theme_id must be non-empty")

    normalized_policy = _normalize_policy(policy)
    transition = _source_transition(source_record, theme_id)
    if (
        transition.routing_intent is RoutingIntent.ORDINARY_FULL_RESEARCH
        and research_mode is not ResearchMode.COMPANY_DEEP_DIVE
    ):
        raise ValueError(
            "routing state is not executable in research v0.1"
        )

    eligible_full = {
        RoutingIntent.ORDINARY_FULL_RESEARCH,
        RoutingIntent.FORCED_FULL_REVIEW,
    }
    if transition.routing_intent is RoutingIntent.FORCED_REVIEW_UNREGISTERED:
        if research_mode is not ResearchMode.THEME_REASSESSMENT:
            raise ValueError(
                "unregistered forced review cannot create company deep dive"
            )
        if theme_package is not None or tuple(target_tickers):
            raise ValueError(
                "unregistered forced review cannot create company deep dive"
            )
        authorization = ResearchAuthorization.UNREGISTERED_FORCED_REVIEW
        adapter_name = None
        package_version = None
        universe_version = None
        targets = ()
    elif transition.routing_intent in eligible_full:
        if theme_package is None:
            raise ValueError("registered research requires ThemePackage")
        package_version, universe_version = _validate_package_lineage(
            source_record,
            theme_id,
            theme_package,
        )
        authorization = ResearchAuthorization.ALLOCATED_FULL
        adapter_name = theme_package.evidence_adapter
        if research_mode is ResearchMode.COMPANY_DEEP_DIVE:
            targets = _build_targets(
                theme_package,
                _effective_cycle_date(source_record.cycle_as_of),
                target_tickers,
            )
            _company_dimensions(adapter_name, normalized_policy)
        else:
            if tuple(target_tickers):
                raise ValueError(
                    "theme reassessment does not accept company targets"
                )
            targets = ()
    else:
        raise ValueError(
            "routing state is not executable in research v0.1"
        )

    if (
        transition.source_tier is None
        or transition.source_forced_review is None
    ):
        raise ValueError(
            "routing state is not executable in research v0.1"
        )

    requirements = _build_requirements(
        mode=research_mode,
        targets=targets,
        adapter_name=adapter_name,
        policy=normalized_policy,
    )
    policy_hash = canonical_hash(asdict(normalized_policy))
    contradiction_questions = (
        _CONTRADICTION_QUESTIONS
        if transition.source_forced_review
        else ()
    )

    seed = ResearchWorkOrder(
        schema_version=SCHEMA_VERSION,
        source_archive_record_hash=source_record.archive_record_hash,
        source_replay_result_hash=source_record.replay_result_hash,
        source_cycle_as_of=source_record.cycle_as_of,
        theme_id=theme_id,
        source_routing_intent=transition.routing_intent,
        source_registered=transition.source_registered,
        source_allocated_tier=transition.source_tier,
        source_forced_review=transition.source_forced_review,
        authorization=authorization,
        research_mode=research_mode,
        evidence_adapter=adapter_name,
        package_version=package_version,
        universe_version=universe_version,
        package_lineage_exactly_recoverable=False,
        targets=targets,
        requirements=requirements,
        minimum_independent_sources=(
            normalized_policy.minimum_independent_sources
        ),
        minimum_independent_sources_per_company=(
            normalized_policy.minimum_independent_sources_per_company
        ),
        contradiction_questions=contradiction_questions,
        policy_hash=policy_hash,
        work_order_hash="0" * 64,
    )
    order = replace(
        seed,
        work_order_hash=canonical_hash(
            _work_order_payload_without_hash(seed)
        ),
    )
    _validate_work_order_hash(order)
    return order



class ResearchEvidenceDirection(str, Enum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class ResearchEvidenceInput:
    evidence: EvidenceRecord
    independent: bool
    direction: ResearchEvidenceDirection
    dimensions: tuple[str, ...]
    target_ticker: str | None


@dataclass(frozen=True)
class FrozenResearchEvidence:
    evidence_id: str
    source_hash: str
    payload_hash: str
    observed_at: str
    retrieved_at: str | None
    market_asof: str | None
    ticker: str | None
    theme: str | None
    source_type: str
    source_ref: str
    fact_type: str
    is_observed_fact: bool
    model_version: str | None
    notes: str | None


@dataclass(frozen=True)
class ResearchEvidenceBinding:
    evidence: FrozenResearchEvidence
    independent: bool
    direction: ResearchEvidenceDirection
    dimensions: tuple[str, ...]
    target_ticker: str | None


class ResearchFindingKind(str, Enum):
    OBSERVED_SYNTHESIS = "OBSERVED_SYNTHESIS"
    INFERENCE = "INFERENCE"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class ResearchFinding:
    finding_id: str
    kind: ResearchFindingKind
    direction: ResearchEvidenceDirection | None
    dimension: str
    target_ticker: str | None
    statement: str
    evidence_source_hashes: tuple[str, ...]


class ResearchExecutionClosure(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


def _validate_evidence_record(record: EvidenceRecord) -> None:
    digest = record.source_hash
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
    ):
        raise ValueError("invalid research evidence hash")
    payload = asdict(record)
    payload["source_hash"] = None
    if canonical_hash(payload) != digest:
        raise ValueError("invalid research evidence hash")


def _freeze_evidence(
    item: ResearchEvidenceInput,
    *,
    order: ResearchWorkOrder,
    evidence_as_of: datetime,
) -> ResearchEvidenceBinding:
    evidence = item.evidence
    _validate_evidence_record(evidence)
    if not isinstance(item.independent, bool):
        raise TypeError("independent must be bool")
    if not isinstance(item.direction, ResearchEvidenceDirection):
        raise TypeError("unsupported research evidence direction")
    if (
        item.independent
        and (
            evidence.source_type == "radar_model_output"
            or not evidence.is_observed_fact
        )
    ):
        raise ValueError(
            "model or inferred evidence cannot be marked independent"
        )

    for value in (
        evidence.observed_at,
        evidence.market_asof,
        evidence.retrieved_at,
    ):
        if value is not None and _parse_utc(value) > evidence_as_of:
            raise ValueError("research evidence exceeds evidence_as_of")

    targets = {target.ticker for target in order.targets}
    ticker = None if evidence.ticker is None else evidence.ticker.upper()
    target_ticker = (
        None
        if item.target_ticker is None
        else item.target_ticker.strip().upper()
    )
    if evidence.theme is not None and evidence.theme != order.theme_id:
        raise ValueError("research evidence is outside work-order scope")
    if ticker is not None and ticker not in targets:
        raise ValueError("research evidence is outside work-order scope")
    if evidence.theme is None and ticker is None:
        raise ValueError("research evidence is outside work-order scope")
    if order.research_mode is ResearchMode.THEME_REASSESSMENT:
        if target_ticker is not None or ticker is not None:
            raise ValueError("theme reassessment requires theme-level evidence")
    elif target_ticker not in targets:
        raise ValueError("research evidence target is outside work-order scope")
    if (
        target_ticker is not None
        and ticker is not None
        and ticker != target_ticker
    ):
        raise ValueError(
            "ticker-specific evidence does not match binding target"
        )

    dimensions = _normalize_dimensions(
        item.dimensions,
        field_name="research evidence dimensions",
    )
    frozen = FrozenResearchEvidence(
        evidence_id=evidence.evidence_id,
        source_hash=evidence.source_hash,
        payload_hash=canonical_hash(evidence.payload),
        observed_at=evidence.observed_at,
        retrieved_at=evidence.retrieved_at,
        market_asof=evidence.market_asof,
        ticker=ticker,
        theme=evidence.theme,
        source_type=str(evidence.source_type),
        source_ref=evidence.source_ref,
        fact_type=evidence.fact_type,
        is_observed_fact=evidence.is_observed_fact,
        model_version=evidence.model_version,
        notes=evidence.notes,
    )
    return ResearchEvidenceBinding(
        evidence=frozen,
        independent=item.independent,
        direction=item.direction,
        dimensions=dimensions,
        target_ticker=target_ticker,
    )


def _freeze_evidence_inputs(
    inputs: Sequence[ResearchEvidenceInput],
    *,
    order: ResearchWorkOrder,
    evidence_as_of: datetime,
) -> tuple[
    tuple[ResearchEvidenceBinding, ...],
    dict[str, EvidenceRecord],
]:
    bindings: list[ResearchEvidenceBinding] = []
    originals: dict[str, EvidenceRecord] = {}
    source_metadata: dict[str, tuple[bool, str]] = {}
    for item in inputs:
        binding = _freeze_evidence(
            item,
            order=order,
            evidence_as_of=evidence_as_of,
        )
        digest = binding.evidence.source_hash
        if digest in originals:
            raise ValueError("duplicate research evidence hash")
        metadata = (
            binding.independent,
            binding.evidence.source_type,
        )
        previous = source_metadata.get(binding.evidence.source_ref)
        if previous is not None and previous != metadata:
            raise ValueError("conflicting research source metadata")
        source_metadata[binding.evidence.source_ref] = metadata
        originals[digest] = item.evidence
        bindings.append(binding)

    return (
        tuple(
            sorted(
                bindings,
                key=lambda item: (
                    item.evidence.source_hash,
                    item.target_ticker or "",
                    item.direction.value,
                    item.dimensions,
                ),
            )
        ),
        originals,
    )


def _normalize_findings(
    findings: Sequence[ResearchFinding],
    *,
    order: ResearchWorkOrder,
    evidence: Mapping[str, EvidenceRecord],
) -> tuple[ResearchFinding, ...]:
    targets = {target.ticker for target in order.targets}
    output: list[ResearchFinding] = []
    seen_ids: set[str] = set()
    for item in findings:
        if not isinstance(item.kind, ResearchFindingKind):
            raise TypeError("unsupported research finding kind")
        if (
            item.direction is not None
            and not isinstance(item.direction, ResearchEvidenceDirection)
        ):
            raise TypeError("unsupported research finding direction")

        finding_id = item.finding_id.strip()
        dimension = item.dimension.strip()
        statement = item.statement.strip()
        if not finding_id or not dimension or not statement:
            raise ValueError("research finding fields must be non-empty")
        if finding_id in seen_ids:
            raise ValueError("duplicate research finding_id")
        seen_ids.add(finding_id)

        target = (
            None
            if item.target_ticker is None
            else item.target_ticker.strip().upper()
        )
        if target is not None and target not in targets:
            raise ValueError("research finding target outside work order")

        hashes = tuple(sorted(item.evidence_source_hashes))
        if len(set(hashes)) != len(hashes):
            raise ValueError("duplicate research finding evidence hash")
        if any(digest not in evidence for digest in hashes):
            raise ValueError("research finding references unknown evidence")

        if item.kind is ResearchFindingKind.UNRESOLVED:
            if item.direction is not None:
                raise ValueError("unresolved finding cannot have direction")
        else:
            if item.direction is None or not hashes:
                raise ValueError(
                    "research finding requires evidence and direction"
                )
            if (
                item.kind is ResearchFindingKind.OBSERVED_SYNTHESIS
                and any(
                    not evidence[digest].is_observed_fact
                    for digest in hashes
                )
            ):
                raise ValueError(
                    "observed synthesis requires observed evidence"
                )

        for digest in hashes:
            record = evidence[digest]
            record_ticker = (
                None if record.ticker is None else record.ticker.upper()
            )
            if (
                target is not None
                and record_ticker not in (None, target)
            ):
                raise ValueError(
                    "research finding cites another target company"
                )

        output.append(
            ResearchFinding(
                finding_id=finding_id,
                kind=item.kind,
                direction=item.direction,
                dimension=dimension,
                target_ticker=target,
                statement=statement,
                evidence_source_hashes=hashes,
            )
        )
    return tuple(sorted(output, key=lambda item: item.finding_id))



@dataclass(frozen=True)
class CompanyResearchSubmission:
    ticker: str
    as_of: str
    adapter_name: str
    raw_facts: Mapping[str, RawFactValue]
    evidence_source_hashes: tuple[str, ...]


@dataclass(frozen=True)
class NormalizedCompanyField:
    name: str
    value: float | int | str


@dataclass(frozen=True)
class NormalizedCompanySnapshot:
    ticker: str
    as_of: str
    adapter_name: str
    source_coverage: str
    provenance: tuple[str, ...]
    fields: tuple[NormalizedCompanyField, ...]
    normalized_payload_hash: str


@dataclass(frozen=True)
class CompanyLinkageSubmission:
    ticker: str
    linkage: LinkageResult | None = None
    hierarchical_linkage: HierarchicalLinkageResult | None = None


@dataclass(frozen=True)
class HierarchicalLinkageSnapshot:
    target: str
    status: str
    window: int
    observations: int
    theme_correlation: float | None
    theme_beta: float | None
    r2: float | None
    incremental_theme_r2: float | None
    residual_mean: float | None
    residual_vol: float | None
    circularity_warning: bool
    missing_controls: tuple[str, ...]
    coefficients: tuple[tuple[str, float], ...]
    source_payload_hash: str


class CompanyLinkageStatus(str, Enum):
    USABLE = "USABLE"
    COVERAGE_PENDING = "COVERAGE_PENDING"
    CIRCULARITY_WARNING = "CIRCULARITY_WARNING"
    NOT_PROVIDED = "NOT_PROVIDED"


@dataclass(frozen=True)
class CompanyResearchAssessment:
    ticker: str
    normalized_evidence: NormalizedCompanySnapshot | None
    evidence_source_hashes: tuple[str, ...]
    independent_source_count: int
    covered_dimensions: tuple[str, ...]
    linkage_status: CompanyLinkageStatus
    linkage: LinkageResult | None
    hierarchical_linkage: HierarchicalLinkageSnapshot | None
    cautions: tuple[str, ...]


def _canonical_raw_facts(
    raw_facts: Mapping[str, RawFactValue],
) -> dict[str, RawFactValue]:
    output: dict[str, RawFactValue] = {}
    for key, value in raw_facts.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("company raw-fact key must be non-empty")
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float, str))
        ):
            raise TypeError("unsupported company raw-fact value")
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("company raw-fact value must be finite")
        output[key.strip()] = value
    return output


def _adapter_for(name: str):
    if name == "industrials_infrastructure":
        return IndustrialsInfrastructureAdapter()
    if name == "biotech_clinical":
        return BiotechClinicalAdapter()
    if name == "generic":
        raise ValueError(
            "generic adapter is not eligible for company deep dive"
        )
    raise ValueError("unsupported company evidence adapter")


def _snapshot_normalized(
    normalized,
    *,
    adapter_name: str,
) -> NormalizedCompanySnapshot:
    payload = asdict(normalized)
    digest = canonical_hash(payload)
    excluded = {
        "ticker",
        "as_of",
        "source_coverage",
        "provenance",
        "raw_facts",
    }
    output_fields: list[NormalizedCompanyField] = []
    for field in fields(normalized):
        if field.name in excluded:
            continue
        value = getattr(normalized, field.name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(
            value,
            (int, float, str),
        ):
            raise TypeError("unsupported normalized company field type")
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("normalized company field must be finite")
        output_fields.append(
            NormalizedCompanyField(field.name, value)
        )
    return NormalizedCompanySnapshot(
        ticker=normalized.ticker,
        as_of=normalized.as_of,
        adapter_name=adapter_name,
        source_coverage=normalized.source_coverage,
        provenance=tuple(normalized.provenance),
        fields=tuple(
            sorted(output_fields, key=lambda item: item.name)
        ),
        normalized_payload_hash=digest,
    )


def _canonical_value_equal(left, right) -> bool:
    return canonical_hash({"value": left}) == canonical_hash(
        {"value": right}
    )


def _normalize_company_submissions(
    submissions: Sequence[CompanyResearchSubmission],
    *,
    order: ResearchWorkOrder,
    evidence: Mapping[str, EvidenceRecord],
    evidence_as_of: datetime,
) -> dict[str, NormalizedCompanySnapshot]:
    targets = {target.ticker for target in order.targets}
    output: dict[str, NormalizedCompanySnapshot] = {}
    for submission in submissions:
        ticker = submission.ticker.strip().upper()
        if ticker not in targets:
            raise ValueError("company submission target outside work order")
        if ticker in output:
            raise ValueError("duplicate company research submission")
        if submission.adapter_name != order.evidence_adapter:
            raise ValueError("company adapter does not match work order")
        company_as_of = _parse_utc(submission.as_of)
        source_as_of = _parse_utc(order.source_cycle_as_of)
        if company_as_of < source_as_of or company_as_of > evidence_as_of:
            raise ValueError(
                "company research as_of is outside execution window"
            )

        hashes = tuple(sorted(submission.evidence_source_hashes))
        if len(set(hashes)) != len(hashes):
            raise ValueError("duplicate company evidence hash")
        if any(digest not in evidence for digest in hashes):
            raise ValueError(
                "company submission references unknown evidence"
            )
        for digest in hashes:
            record = evidence[digest]
            record_ticker = (
                None
                if record.ticker is None
                else record.ticker.upper()
            )
            if record_ticker not in (None, ticker):
                raise ValueError(
                    "company submission cites another target company"
                )

        raw_facts = _canonical_raw_facts(submission.raw_facts)
        for key, value in raw_facts.items():
            supported = any(
                record.ticker is not None
                and record.ticker.upper() == ticker
                and key in record.payload
                and _canonical_value_equal(
                    record.payload[key],
                    value,
                )
                for digest, record in evidence.items()
                if digest in hashes
            )
            if not supported:
                raise ValueError(
                    "company raw fact is unsupported by cited evidence"
                )

        normalized = _adapter_for(
            submission.adapter_name
        ).normalize(
            CompanyEvidenceInput(
                ticker=ticker,
                as_of=submission.as_of,
                raw_facts=dict(raw_facts),
                provenance=hashes,
            )
        )
        output[ticker] = _snapshot_normalized(
            normalized,
            adapter_name=submission.adapter_name,
        )
    return output


def _finite_optional(value, *, field_name: str) -> None:
    if value is not None and not isfinite(float(value)):
        raise ValueError(f"{field_name} must be finite")


def _snapshot_hierarchical_linkage(
    value: HierarchicalLinkageResult,
) -> HierarchicalLinkageSnapshot:
    for name in (
        "theme_correlation",
        "theme_beta",
        "r2",
        "incremental_theme_r2",
        "residual_mean",
        "residual_vol",
    ):
        _finite_optional(getattr(value, name), field_name=name)
    coefficients = tuple(
        sorted(
            (
                str(name),
                float(coefficient),
            )
            for name, coefficient in value.coefficients.items()
        )
    )
    if any(
        not isfinite(coefficient)
        for _, coefficient in coefficients
    ):
        raise ValueError("linkage coefficient must be finite")
    return HierarchicalLinkageSnapshot(
        target=value.target.upper(),
        status=value.status,
        window=value.window,
        observations=value.observations,
        theme_correlation=value.theme_correlation,
        theme_beta=value.theme_beta,
        r2=value.r2,
        incremental_theme_r2=value.incremental_theme_r2,
        residual_mean=value.residual_mean,
        residual_vol=value.residual_vol,
        circularity_warning=value.circularity_warning,
        missing_controls=tuple(value.missing_controls),
        coefficients=coefficients,
        source_payload_hash=canonical_hash(asdict(value)),
    )


def _validate_simple_linkage(
    value: LinkageResult,
    ticker: str,
) -> LinkageResult:
    if value.ticker.upper() != ticker:
        raise ValueError("linkage ticker mismatch")
    for name in (
        "correlation",
        "beta",
        "r2",
        "residual_mean",
        "residual_vol",
        "beta_stability",
        "decoupling_score",
    ):
        _finite_optional(getattr(value, name), field_name=name)
    return value


def _linkage_status(
    linkage: LinkageResult | None,
    hierarchical: HierarchicalLinkageSnapshot | None,
) -> CompanyLinkageStatus:
    if linkage is None and hierarchical is None:
        return CompanyLinkageStatus.NOT_PROVIDED
    if (
        (linkage is not None and linkage.circularity_warning)
        or (
            hierarchical is not None
            and hierarchical.circularity_warning
        )
    ):
        return CompanyLinkageStatus.CIRCULARITY_WARNING
    if (
        hierarchical is not None
        and hierarchical.status == "ok"
    ):
        return CompanyLinkageStatus.USABLE
    if (
        linkage is not None
        and linkage.correlation is not None
        and linkage.beta is not None
        and linkage.r2 is not None
    ):
        return CompanyLinkageStatus.USABLE
    return CompanyLinkageStatus.COVERAGE_PENDING


def _normalize_linkage_submissions(
    submissions: Sequence[CompanyLinkageSubmission],
    *,
    order: ResearchWorkOrder,
) -> dict[
    str,
    tuple[
        LinkageResult | None,
        HierarchicalLinkageSnapshot | None,
    ],
]:
    targets = {target.ticker for target in order.targets}
    output: dict[
        str,
        tuple[
            LinkageResult | None,
            HierarchicalLinkageSnapshot | None,
        ],
    ] = {}
    for submission in submissions:
        ticker = submission.ticker.strip().upper()
        if ticker not in targets:
            raise ValueError("linkage target outside work order")
        if ticker in output:
            raise ValueError("duplicate company linkage submission")
        if (
            submission.linkage is None
            and submission.hierarchical_linkage is None
        ):
            raise ValueError("linkage submission is empty")

        simple = (
            None
            if submission.linkage is None
            else _validate_simple_linkage(
                submission.linkage,
                ticker,
            )
        )
        hierarchical = None
        if submission.hierarchical_linkage is not None:
            if (
                submission.hierarchical_linkage.target.upper()
                != ticker
            ):
                raise ValueError("linkage ticker mismatch")
            hierarchical = _snapshot_hierarchical_linkage(
                submission.hierarchical_linkage
            )
        output[ticker] = (simple, hierarchical)
    return output


def _build_company_assessments(
    *,
    order: ResearchWorkOrder,
    bindings: tuple[ResearchEvidenceBinding, ...],
    company_snapshots: Mapping[str, NormalizedCompanySnapshot],
    linkage_map: Mapping[
        str,
        tuple[
            LinkageResult | None,
            HierarchicalLinkageSnapshot | None,
        ],
    ],
) -> tuple[CompanyResearchAssessment, ...]:
    rows: list[CompanyResearchAssessment] = []
    for target in order.targets:
        ticker = target.ticker
        linkage, hierarchical = linkage_map.get(
            ticker,
            (None, None),
        )
        status = _linkage_status(linkage, hierarchical)
        independent_refs = {
            item.evidence.source_ref
            for item in bindings
            if item.target_ticker == ticker and item.independent
        }
        normalized = company_snapshots.get(ticker)
        covered_dimensions = (
            ()
            if normalized is None
            else tuple(
                field.name
                for field in normalized.fields
            )
        )
        evidence_hashes = tuple(
            sorted(
                item.evidence.source_hash
                for item in bindings
                if item.target_ticker == ticker
            )
        )
        cautions: list[str] = []
        if status is CompanyLinkageStatus.COVERAGE_PENDING:
            cautions.append("linkage coverage pending")
        elif status is CompanyLinkageStatus.CIRCULARITY_WARNING:
            cautions.append("linkage circularity warning")
        if (
            len(independent_refs)
            < order.minimum_independent_sources_per_company
        ):
            cautions.append("independent source minimum not met")

        rows.append(
            CompanyResearchAssessment(
                ticker=ticker,
                normalized_evidence=normalized,
                evidence_source_hashes=evidence_hashes,
                independent_source_count=len(independent_refs),
                covered_dimensions=covered_dimensions,
                linkage_status=status,
                linkage=linkage,
                hierarchical_linkage=hierarchical,
                cautions=tuple(cautions),
            )
        )
    return tuple(rows)



class ResearchDossierStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    BLOCKED_INSUFFICIENT_EVIDENCE = "BLOCKED_INSUFFICIENT_EVIDENCE"


_DOSSIER_LIMITATIONS = (
    "research completion means required coverage, not thesis correctness",
    "allocation tier does not prove research execution without a dossier",
    "provider retrieval and extraction occur outside this module",
    "theme package exact historical bytes are not recoverable from ReplayCycleResult alone",
    "research dossier does not grant trading permission",
    "evidence payload content is committed by hash but not embedded in the dossier",
)


@dataclass(frozen=True)
class ResearchDossier:
    schema_version: str
    work_order_hash: str
    source_archive_record_hash: str
    source_cycle_as_of: str
    theme_id: str
    research_mode: ResearchMode
    evidence_as_of: str
    closure: ResearchExecutionClosure
    status: ResearchDossierStatus
    evidence_bindings: tuple[ResearchEvidenceBinding, ...]
    independent_source_count: int
    satisfied_requirements: tuple[ResearchRequirement, ...]
    unsatisfied_requirements: tuple[ResearchRequirement, ...]
    company_assessments: tuple[CompanyResearchAssessment, ...]
    findings: tuple[ResearchFinding, ...]
    contradictions_present: bool
    unresolved_present: bool
    limitations: tuple[str, ...]
    input_hash: str
    dossier_hash: str


def _linkage_input_payload(
    submission: CompanyLinkageSubmission,
) -> dict[str, object]:
    ticker = submission.ticker.strip().upper()
    simple = (
        None
        if submission.linkage is None
        else asdict(
            _validate_simple_linkage(
                submission.linkage,
                ticker,
            )
        )
    )
    hierarchical = (
        None
        if submission.hierarchical_linkage is None
        else asdict(
            _snapshot_hierarchical_linkage(
                submission.hierarchical_linkage
            )
        )
    )
    return {
        "ticker": ticker,
        "linkage": simple,
        "hierarchical_linkage": hierarchical,
    }


def _requirement_satisfied(
    requirement: ResearchRequirement,
    *,
    bindings: tuple[ResearchEvidenceBinding, ...],
    assessments: Mapping[str, CompanyResearchAssessment],
) -> bool:
    if requirement.scope is ResearchRequirementScope.THEME_EVIDENCE:
        return any(
            item.target_ticker is None
            and requirement.dimension in item.dimensions
            for item in bindings
        )

    assert requirement.target_ticker is not None
    assessment = assessments[requirement.target_ticker]
    if requirement.scope is ResearchRequirementScope.COMPANY_LINKAGE:
        return (
            assessment.linkage_status
            is CompanyLinkageStatus.USABLE
        )

    binding_coverage = any(
        item.target_ticker == requirement.target_ticker
        and requirement.dimension in item.dimensions
        for item in bindings
    )
    normalized_coverage = (
        assessment.normalized_evidence is not None
        and requirement.dimension in assessment.covered_dimensions
    )
    return binding_coverage and normalized_coverage


def _derive_status(
    *,
    complete: bool,
    closure: ResearchExecutionClosure,
    evidence_bindings,
    company_submissions,
    linkage_submissions,
    findings,
) -> ResearchDossierStatus:
    if complete:
        return ResearchDossierStatus.COMPLETE
    if closure is ResearchExecutionClosure.CLOSED:
        return ResearchDossierStatus.BLOCKED_INSUFFICIENT_EVIDENCE
    if not (
        evidence_bindings
        or company_submissions
        or linkage_submissions
        or findings
    ):
        return ResearchDossierStatus.NOT_STARTED
    return ResearchDossierStatus.PARTIAL


def _dossier_payload_without_hash(
    dossier: ResearchDossier,
) -> dict[str, object]:
    payload = asdict(dossier)
    payload.pop("dossier_hash")
    return payload


def build_research_dossier(
    work_order: ResearchWorkOrder,
    *,
    evidence_as_of: str,
    closure: ResearchExecutionClosure,
    evidence_inputs: Sequence[ResearchEvidenceInput] = (),
    company_submissions: Sequence[CompanyResearchSubmission] = (),
    linkage_submissions: Sequence[CompanyLinkageSubmission] = (),
    findings: Sequence[ResearchFinding] = (),
) -> ResearchDossier:
    _validate_work_order_hash(work_order)
    if not isinstance(closure, ResearchExecutionClosure):
        raise TypeError("unsupported research execution closure")
    evidence_as_of_dt = _parse_utc(evidence_as_of)
    if evidence_as_of_dt < _parse_utc(work_order.source_cycle_as_of):
        raise ValueError("evidence_as_of precedes source cycle")

    bindings, originals = _freeze_evidence_inputs(
        evidence_inputs,
        order=work_order,
        evidence_as_of=evidence_as_of_dt,
    )
    canonical_findings = _normalize_findings(
        findings,
        order=work_order,
        evidence=originals,
    )
    company_snapshots = _normalize_company_submissions(
        company_submissions,
        order=work_order,
        evidence=originals,
        evidence_as_of=evidence_as_of_dt,
    )
    linkage_map = _normalize_linkage_submissions(
        linkage_submissions,
        order=work_order,
    )
    assessments = _build_company_assessments(
        order=work_order,
        bindings=bindings,
        company_snapshots=company_snapshots,
        linkage_map=linkage_map,
    )
    assessment_by_ticker = {
        item.ticker: item for item in assessments
    }

    satisfied = tuple(
        item
        for item in work_order.requirements
        if _requirement_satisfied(
            item,
            bindings=bindings,
            assessments=assessment_by_ticker,
        )
    )
    satisfied_set = set(satisfied)
    unsatisfied = tuple(
        item
        for item in work_order.requirements
        if item not in satisfied_set
    )

    independent_refs = {
        item.evidence.source_ref
        for item in bindings
        if item.independent
    }
    company_complete = (
        work_order.research_mode
        is ResearchMode.THEME_REASSESSMENT
        or all(
            item.normalized_evidence is not None
            and item.independent_source_count
            >= work_order.minimum_independent_sources_per_company
            for item in assessments
        )
    )
    complete = (
        not unsatisfied
        and len(independent_refs)
        >= work_order.minimum_independent_sources
        and company_complete
    )
    status = _derive_status(
        complete=complete,
        closure=closure,
        evidence_bindings=bindings,
        company_submissions=company_submissions,
        linkage_submissions=linkage_submissions,
        findings=canonical_findings,
    )
    contradictions_present = any(
        item.direction
        is ResearchEvidenceDirection.CONTRADICTING
        for item in bindings
    ) or any(
        item.kind is not ResearchFindingKind.UNRESOLVED
        and item.direction
        is ResearchEvidenceDirection.CONTRADICTING
        for item in canonical_findings
    )
    unresolved_present = any(
        item.kind is ResearchFindingKind.UNRESOLVED
        for item in canonical_findings
    )

    canonical_evidence_as_of = evidence_as_of_dt.isoformat()
    input_payload = {
        "work_order_hash": work_order.work_order_hash,
        "evidence_as_of": canonical_evidence_as_of,
        "closure": closure,
        "evidence_bindings": [
            asdict(item) for item in bindings
        ],
        "company_submissions": [
            {
                "ticker": item.ticker.strip().upper(),
                "as_of": _parse_utc(item.as_of).isoformat(),
                "adapter_name": item.adapter_name,
                "raw_facts": _canonical_raw_facts(
                    item.raw_facts
                ),
                "evidence_source_hashes": sorted(
                    item.evidence_source_hashes
                ),
            }
            for item in sorted(
                company_submissions,
                key=lambda item: item.ticker.upper(),
            )
        ],
        "linkage_submissions": [
            _linkage_input_payload(item)
            for item in sorted(
                linkage_submissions,
                key=lambda item: item.ticker.upper(),
            )
        ],
        "findings": [
            asdict(item) for item in canonical_findings
        ],
    }
    input_hash = canonical_hash(input_payload)

    seed = ResearchDossier(
        schema_version=SCHEMA_VERSION,
        work_order_hash=work_order.work_order_hash,
        source_archive_record_hash=(
            work_order.source_archive_record_hash
        ),
        source_cycle_as_of=work_order.source_cycle_as_of,
        theme_id=work_order.theme_id,
        research_mode=work_order.research_mode,
        evidence_as_of=canonical_evidence_as_of,
        closure=closure,
        status=status,
        evidence_bindings=bindings,
        independent_source_count=len(independent_refs),
        satisfied_requirements=satisfied,
        unsatisfied_requirements=unsatisfied,
        company_assessments=assessments,
        findings=canonical_findings,
        contradictions_present=contradictions_present,
        unresolved_present=unresolved_present,
        limitations=_DOSSIER_LIMITATIONS,
        input_hash=input_hash,
        dossier_hash="0" * 64,
    )
    return replace(
        seed,
        dossier_hash=canonical_hash(
            _dossier_payload_without_hash(seed)
        ),
    )
