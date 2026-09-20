from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from enum import Enum

from .adapters import BiotechClinicalEvidence, NormalizedCompanyEvidence
from .evidence import EvidenceRecord
from .ledger import canonical_hash
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


def _validate_work_order_hash(order: ResearchWorkOrder) -> None:
    if (
        canonical_hash(_work_order_payload_without_hash(order))
        != order.work_order_hash
    ):
        raise ValueError("invalid research work order")


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
