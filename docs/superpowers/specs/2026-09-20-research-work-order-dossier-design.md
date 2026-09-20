# Increment 8 — Research Work Order + Deterministic Research Dossier Design

Date: 2026-09-20
Status: approved in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: feature/research-work-order-dossier

## 1. Purpose

Create the missing execution layer between research allocation and later decision readiness.

Target chain:

    ReplayArchiveRecord
      -> source routing state
      -> ResearchWorkOrder
      -> frozen research evidence
      -> ResearchDossier

The central invariant is:

    research allocated
      != research executed

and:

    research executed
      != trade permitted

Increment 8 makes those distinctions real in the type system.

## 2. Scientific role

Increment 5 created deterministic replay routing.

Increment 6 froze replay history.

Increment 7 evaluated later evidence evolution without pretending allocation meant execution.

Increment 8 now answers:

    Was a research task actually instantiated?
    What evidence was supplied?
    Which requirements were covered?
    Which company facts were normalized?
    Was theme/company linkage usable?
    Was the research execution complete, partial, not started, or blocked?

It does not answer whether to trade.

## 3. Selected architecture

Add one pure module:

    src/decision_lab/research_execution.py

Public workflow:

    build_research_work_order(...)
      -> ResearchWorkOrder

    build_research_dossier(...)
      -> ResearchDossier

Both are deterministic pure functions.

No network, filesystem, ambient clock, random state, provider SDK, or scheduler is used.

## 4. Explicit non-goals

Increment 8 does not add:

- SEC fetching;
- investor-relations fetching;
- news fetching;
- web search;
- brokerage data;
- live market fetching;
- automatic evidence extraction from webpages;
- LLM research calls;
- Tape assessment;
- playbook routing;
- Decision Object compilation;
- entry/invalidation;
- position sizing;
- order execution;
- price-outcome scoring;
- archive directory scanning;
- a new filesystem archive format;
- value-of-research causal estimation;
- a universal company score.

## 5. Why provider-neutral first

External retrieval is an I/O/provider concern.

Research execution semantics are a scientific state-machine concern.

Mixing them would make it impossible to distinguish:

    provider failure

from:

    insufficient evidence

from:

    research not started

from:

    research completed

Increment 8 therefore accepts explicit frozen evidence inputs.

## 6. Why no Tape/Playbook integration yet

Current Tape and Playbook modules answer execution-timing questions.

Increment 8 answers research-completion questions.

The boundary remains:

    ResearchDossier
      != TapeAssessment
      != PlaybookRouting
      != Decision Object

A future increment may combine a complete dossier with fresh Tape state.

## 7. Why no new filesystem archive in v0.1

ResearchWorkOrder and ResearchDossier are frozen dataclasses with deterministic semantic hashes.

Version 0.1 does not add another typed filesystem archive layer.

Reasons:

- WorkOrder/Dossier semantics are new and should stabilize first;
- replay archival already established the persistence pattern;
- filesystem schema, provider ingestion, and execution semantics should not be expanded simultaneously.

A caller may serialize these objects using an explicit immutable storage layer, but Increment 8 itself performs no I/O.

## 8. Core invariants

The following must hold:

    same semantic inputs
      -> same ResearchWorkOrder
      -> same work_order_hash

and:

    same WorkOrder + same frozen research inputs
      -> same ResearchDossier
      -> same dossier_hash

No wall-clock timestamp enters either identity.

## 9. Source replay validation

Research execution begins from:

    ReplayArchiveRecord

Do not trust an arbitrary manually-constructed archive record.

Call:

    evaluate_replay_cohort((record,), horizons=(1,))

as the public semantic validation boundary.

This reuses Increment 7's validated routing semantics instead of duplicating its private routing classifier.

## 10. Source routing extraction

A one-record cohort at horizon 1 emits one right-censored transition per source theme.

For requested theme_id:

- exactly one source transition must exist;
- use its RoutingIntent;
- use its source_registered;
- use its source_tier;
- use source_forced_review and source replay status.

If theme_id is absent:

    raise ValueError("theme missing from source replay")

## 11. Eligible routing states

Version 0.1 supports work-order construction only from:

### ORDINARY_FULL_RESEARCH

Allowed mode:

    COMPANY_DEEP_DIVE

Authorization:

    ALLOCATED_FULL

### FORCED_FULL_REVIEW

Allowed modes:

    THEME_REASSESSMENT
    COMPANY_DEEP_DIVE

Authorization:

    ALLOCATED_FULL

### FORCED_REVIEW_UNREGISTERED

Allowed mode:

    THEME_REASSESSMENT

Authorization:

    UNREGISTERED_FORCED_REVIEW

This does not reinterpret the source tier as FULL.

It preserves the source fact that the unregistered forced review was routed as SCAN_ONLY.

## 12. Ineligible routing states

Reject work-order construction from:

    NO_OBSERVATION
    SCAN_ONLY
    ORDINARY_THEME_RESEARCH
    FORCED_REVIEW_CAPACITY_MISSED

with:

    ValueError("routing state is not executable in research v0.1")

Capacity-missed review must not silently bypass the allocator.

## 13. ResearchMode

Define:

    class ResearchMode(str, Enum):
        THEME_REASSESSMENT = "THEME_REASSESSMENT"
        COMPANY_DEEP_DIVE = "COMPANY_DEEP_DIVE"

## 14. ResearchAuthorization

Define:

    class ResearchAuthorization(str, Enum):
        ALLOCATED_FULL = "ALLOCATED_FULL"
        UNREGISTERED_FORCED_REVIEW = "UNREGISTERED_FORCED_REVIEW"

Authorization records why the work order exists.

It is not a trading permission.

## 15. ThemePackage requirement

COMPANY_DEEP_DIVE requires an explicit ThemePackage.

THEME_REASSESSMENT:

- requires ThemePackage when source theme is registered;
- requires no ThemePackage when source theme is unregistered.

An unregistered forced review cannot manufacture a package just to obtain company targets.

## 16. ThemePackage identity validation

For a registered source:

- package.definition.theme_id must equal requested theme_id;
- package.universe.theme must equal theme_id;
- package definition must be effective at source cycle date;
- package candidates are evaluated at source cycle date;
- package.version and package.universe.version must match the versions exposed by the source replay's MarketObservationBatch diagnostics.

If source diagnostics disagree internally on package/universe version:

    raise ValueError("source replay package lineage is inconsistent")

## 17. Package-lineage limitation

ReplayArchiveRecord does not contain the full semantic ThemeReplayInput.

Therefore Increment 8 can validate package and universe version compatibility, but cannot independently prove the supplied ThemePackage is byte-for-byte the exact package used in the historical replay.

This limitation is explicit in ResearchWorkOrder.

## 18. Explicit company target selection

Version 0.1 does not automatically rank companies.

For COMPANY_DEEP_DIVE the caller must pass:

    target_tickers

Rules:

- non-empty;
- unique after uppercasing;
- every ticker must be an effective candidate in the supplied ThemePackage at source cycle;
- input order does not affect identity;
- stored order is lexical.

This avoids hiding a new company-ranking policy inside the executor.

## 19. Theme reassessment target rule

THEME_REASSESSMENT requires:

    target_tickers == ()

Company targets are not silently inferred.

## 20. ResearchTarget

Define frozen dataclass:

    ResearchTarget
      ticker: str
      layer: str
      membership_state: str
      expression_role: str
      effective_from: str | None
      effective_to: str | None
      provenance: tuple[str, ...]

Targets are copied from the effective historical universe.

## 21. ResearchWorkOrderPolicy

Define frozen dataclass:

    ResearchWorkOrderPolicy
      version: str = "0.1"
      theme_reassessment_dimensions: tuple[str, ...]
      industrials_company_dimensions: tuple[str, ...]
      biotech_company_dimensions: tuple[str, ...]
      minimum_independent_sources: int = 2
      minimum_independent_sources_per_company: int = 1
      require_usable_linkage_for_company: bool = True

All dimension tuples must be unique and non-empty.

Minimum counts must be non-negative integers and not bool.

## 22. Default theme-reassessment dimensions

Default:

    (
      "theme_structure",
      "independent_support",
      "independent_contradiction",
      "universe_integrity",
    )

These are coverage requirements, not scores.

## 23. Generic company adapter boundary

GenericEvidenceAdapter preserves raw facts but does not establish a domain-specific normalized company contract.

Therefore COMPANY_DEEP_DIVE in v0.1 rejects:

    evidence_adapter == "generic"

with:

    ValueError("generic adapter is not eligible for company deep dive")

This avoids a fake universal company-completion standard.

THEME_REASSESSMENT is unaffected because it does not require company normalization.

## 24. Default industrials-company dimensions

For evidence_adapter == "industrials_infrastructure":

    (
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

## 25. Default biotech-company dimensions

For evidence_adapter == "biotech_clinical":

    (
      "clinical_phase",
      "endpoint_status",
      "regulatory_state",
      "cash_runway_months",
      "days_to_material_catalyst",
      "financing_risk",
      "platform_validation",
      "partnered_economics",
    )

## 26. ResearchRequirementScope

Define:

    class ResearchRequirementScope(str, Enum):
        THEME_EVIDENCE = "THEME_EVIDENCE"
        COMPANY_EVIDENCE = "COMPANY_EVIDENCE"
        COMPANY_LINKAGE = "COMPANY_LINKAGE"

## 27. ResearchRequirement

Define frozen dataclass:

    ResearchRequirement
      scope: ResearchRequirementScope
      dimension: str
      target_ticker: str | None

Rules:

- THEME_EVIDENCE requires target_ticker is None;
- COMPANY_EVIDENCE requires target_ticker is not None;
- COMPANY_LINKAGE requires dimension == "theme_linkage" and target_ticker is not None.

## 28. Work-order requirement generation

THEME_REASSESSMENT:

- create one THEME_EVIDENCE requirement per theme-reassessment dimension.

COMPANY_DEEP_DIVE:

For every target ticker:

- create one COMPANY_EVIDENCE requirement per resolved adapter-specific dimension;
- if policy.require_usable_linkage_for_company is True, add one COMPANY_LINKAGE requirement with dimension "theme_linkage".

Requirement ordering:

    (scope.value, target_ticker or "", dimension)

## 29. Contradiction questions

ResearchWorkOrder stores:

    contradiction_questions: tuple[str, ...]

For FORCED_FULL_REVIEW and FORCED_REVIEW_UNREGISTERED use fixed v0.1 questions:

    (
      "What independent evidence contradicts the current theme thesis?",
      "Is the contradiction persistent, structural, or coverage-related?",
      "What evidence would resolve rather than merely remove the contradiction?",
    )

For ordinary full research:

    ()

These are research prompts, not answers.

## 30. ResearchWorkOrder

Define frozen dataclass:

    ResearchWorkOrder
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

## 31. Work-order semantic hash

Compute policy_hash from the complete ResearchWorkOrderPolicy semantic payload.

Compute work_order_hash from all ResearchWorkOrder fields except work_order_hash.

No self-reference.

## 32. No hidden source timestamp

ResearchWorkOrder contains source_cycle_as_of from the replay.

It does not add:

    created_at
    generated_at
    datetime.now

Operational wall-clock metadata is outside the semantic object.

## 33. Research evidence input

Increment 8 accepts explicit ResearchEvidenceInput values:

    ResearchEvidenceInput
      evidence: EvidenceRecord
      independent: bool
      direction: ResearchEvidenceDirection
      dimensions: tuple[str, ...]
      target_ticker: str | None

It must not call:

    make_evidence()

because make_evidence assigns retrieved_at from the ambient clock.

ResearchEvidenceInput is an input container only; the final dossier does not retain the mutable EvidenceRecord.payload mapping directly.

## 34. EvidenceRecord hash validation

For every EvidenceRecord:

- source_hash must be a lowercase 64-character SHA-256 hex string;
- recompute the hash from asdict(record) with source_hash set to None;
- require equality.

If not:

    raise ValueError("invalid research evidence hash")

EvidenceRecord.with_hash is not sufficient validation because it trusts an already-populated source_hash.

## 35. ResearchEvidenceDirection

Define:

    class ResearchEvidenceDirection(str, Enum):
        SUPPORTING = "SUPPORTING"
        CONTRADICTING = "CONTRADICTING"
        NEUTRAL = "NEUTRAL"

Direction means relevance to the current research question.

It is not a trade direction.

## 36. FrozenResearchEvidence and ResearchEvidenceBinding

Define frozen dataclass:

    FrozenResearchEvidence
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

payload_hash is:

    canonical_hash(evidence.payload)

The payload itself is not embedded in the dossier. Its complete content remains committed by EvidenceRecord.source_hash and payload_hash.

Define frozen canonical output dataclass:

    ResearchEvidenceBinding
      evidence: FrozenResearchEvidence
      independent: bool
      direction: ResearchEvidenceDirection
      dimensions: tuple[str, ...]
      target_ticker: str | None

Rules:

- dimensions non-empty, unique, lexical;
- target_ticker uppercased when present;
- target ticker must belong to work-order targets;
- theme-level work may use target_ticker None only;
- company deep dive may contain theme-level bindings and company-target bindings;
- unrelated ticker/theme evidence is rejected.

## 37. Evidence scope validation

An EvidenceRecord is in scope when at least one is true:

- record.theme == work_order.theme_id;
- record.ticker is one of work_order target tickers.

If record.theme is non-None and differs from work_order.theme_id:

    reject.

If record.ticker is non-None and is not a work-order target:

    reject.

A completely unbound record with both theme and ticker None is rejected.

## 38. Evidence cutoff

build_research_dossier requires explicit:

    evidence_as_of: str

No ambient clock is used.

Every evidence:

    observed_at <= evidence_as_of

when interpreted as UTC timestamps/dates.

If market_asof is present:

    market_asof <= evidence_as_of

If retrieved_at is present:

    retrieved_at <= evidence_as_of

Future evidence is rejected:

    ValueError("research evidence exceeds evidence_as_of")

## 39. Evidence identity and duplicates

Evidence identity for dossier references is:

    EvidenceRecord.source_hash

Duplicate source_hash inputs are rejected.

Findings and company submissions reference source_hash, not evidence_id.

Reason:

EvidenceRecord.evidence_id does not commit to the entire evidence payload.

## 40. Independent-source counting

Independent source count is based on unique:

    source_ref

among ResearchEvidenceBinding values with:

    independent is True

Multiple evidence records from the same source_ref count once.

The executor does not infer independence positively from source_type.

The caller must state the independence claim explicitly.

However fail-closed guards apply:

- source_type == "radar_model_output" cannot be marked independent;
- evidence.is_observed_fact == False cannot be marked independent.

These inputs raise:

    ValueError("model or inferred evidence cannot be marked independent")

Derived features may be marked independent only when their underlying EvidenceRecord is explicitly marked observed fact.

## 41. Independence-metadata consistency

For the same source_ref within one dossier:

    independent
    source_type

must each be consistent across all bindings.

Conflict raises:

    ValueError("conflicting research source metadata")

This prevents one source from being counted under incompatible independence/source identities.

## 42. Requirement coverage from evidence

A THEME_EVIDENCE requirement is satisfied if at least one valid binding has:

    target_ticker is None
    requirement.dimension in binding.dimensions

A COMPANY_EVIDENCE requirement is satisfied only if both are true:

1. at least one valid binding has:

       target_ticker == requirement.target_ticker
       requirement.dimension in binding.dimensions

2. the target's normalized company evidence has a non-None field with the exact requirement.dimension name.

Therefore a binding cannot merely claim that a dimension was covered while the adapter produced no corresponding normalized value.

Coverage is traceability + usable normalized field presence.

It is not a positive thesis verdict.

## 43. CompanyResearchSubmission

Define frozen dataclass:

    CompanyResearchSubmission
      ticker: str
      as_of: str
      adapter_name: str
      raw_facts: Mapping[str, RawFactValue]
      evidence_source_hashes: tuple[str, ...]

Rules:

- ticker must be a work-order target;
- one submission per target;
- adapter_name must equal work_order.evidence_adapter;
- evidence_source_hashes unique and lexical;
- every referenced hash must exist in dossier evidence;
- every referenced evidence record must be bound to the same ticker or the work-order theme;
- evidence cited as raw-fact support must be ticker-specific to the submission ticker.

## 44. Raw-fact support rule

Every:

    raw_facts[key] = value

must appear with type-sensitive canonical semantic equality in at least one cited ticker-specific EvidenceRecord.payload.

Use:

    canonical_hash({"value": evidence.payload[key]})
      == canonical_hash({"value": value})

rather than permissive Python equality, so True is not treated as 1 and 1 is not silently treated as 1.0.

Otherwise:

    ValueError("company raw fact is unsupported by cited evidence")

This prevents normalized company research from containing uncited facts.

## 45. Company adapter dispatch

Version 0.1 supports:

    "industrials_infrastructure"
      -> IndustrialsInfrastructureAdapter

    "biotech_clinical"
      -> BiotechClinicalAdapter

GenericEvidenceAdapter is intentionally not used for COMPANY_DEEP_DIVE in v0.1.

Unknown adapter names raise:

    ValueError("unsupported company evidence adapter")

The adapter is deterministic and performs no I/O.

## 46. Company normalized evidence

For every CompanyResearchSubmission, build:

    CompanyEvidenceInput(
      ticker,
      as_of,
      raw_facts,
      provenance=evidence_source_hashes,
    )

Then normalize using the validated adapter.

Do not store the adapter's mutable raw_facts mapping inside the final dossier.

Instead convert the normalized object into an immutable snapshot:

    NormalizedCompanyField
      name: str
      value: float | int | str

    NormalizedCompanySnapshot
      ticker: str
      as_of: str
      adapter_name: str
      source_coverage: str
      provenance: tuple[str, ...]
      fields: tuple[NormalizedCompanyField, ...]
      normalized_payload_hash: str

fields contains every non-None normalized public field except:

    ticker
    as_of
    source_coverage
    provenance
    raw_facts

ordered lexically by field name.

normalized_payload_hash commits to the complete asdict(normalized_evidence), including raw_facts, before the mutable mapping is discarded from the output.

## 47. CompanyEvidence as-of validation

CompanyResearchSubmission.as_of must be <= evidence_as_of.

It must not precede the source cycle date.

If outside that half-open execution interval:

    raise ValueError("company research as_of is outside execution window")

## 48. Linkage input and immutable snapshots

Define frozen input dataclass:

    CompanyLinkageSubmission
      ticker: str
      linkage: LinkageResult | None = None
      hierarchical_linkage: HierarchicalLinkageSnapshot | None = None

Rules:

- ticker must be a work-order target;
- at least one linkage object must be supplied;
- linkage.ticker and/or hierarchical.target must equal ticker;
- one submission per target.

No linkage calculation is performed inside Increment 8.

LinkageResult contains only immutable scalar fields and may be copied directly.

HierarchicalLinkageResult contains a mutable coefficients mapping. The final dossier therefore stores:

    HierarchicalLinkageSnapshot
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

coefficients are lexical by control name.

source_payload_hash commits to asdict(HierarchicalLinkageResult) before snapshot conversion.

## 49. CompanyLinkageStatus

Define:

    class CompanyLinkageStatus(str, Enum):
        USABLE = "USABLE"
        COVERAGE_PENDING = "COVERAGE_PENDING"
        CIRCULARITY_WARNING = "CIRCULARITY_WARNING"
        NOT_PROVIDED = "NOT_PROVIDED"

## 50. Linkage-status derivation

CIRCULARITY_WARNING if any supplied linkage object has:

    circularity_warning is True

Otherwise USABLE if either:

- HierarchicalLinkageResult.status == "ok";
- LinkageResult has correlation, beta, and r2 all non-None.

Otherwise:

    COVERAGE_PENDING

No linkage submission:

    NOT_PROVIDED

## 51. Linkage requirement coverage

A COMPANY_LINKAGE requirement is satisfied only when target linkage status is:

    USABLE

CIRCULARITY_WARNING and COVERAGE_PENDING do not satisfy completion.

This prevents an identity-like or under-covered control from supporting a strong completed research state.

## 52. CompanyResearchAssessment

Define frozen dataclass:

    CompanyResearchAssessment
      ticker: str
      normalized_evidence: NormalizedCompanySnapshot
      evidence_source_hashes: tuple[str, ...]
      independent_source_count: int
      covered_dimensions: tuple[str, ...]
      linkage_status: CompanyLinkageStatus
      linkage: LinkageResult | None
      hierarchical_linkage: HierarchicalLinkageResult | None
      cautions: tuple[str, ...]

Cautions include:

- "linkage coverage pending";
- "linkage circularity warning";
- "independent source minimum not met".

## 53. No universal company score

CompanyResearchAssessment contains no:

    company_score
    rank
    probability
    conviction_score

Industrial and biotech normalized fields retain their domain-specific semantics.

## 54. ResearchFindingKind

Define:

    class ResearchFindingKind(str, Enum):
        OBSERVED_SYNTHESIS = "OBSERVED_SYNTHESIS"
        INFERENCE = "INFERENCE"
        UNRESOLVED = "UNRESOLVED"

## 55. ResearchFinding

Define frozen dataclass:

    ResearchFinding
      finding_id: str
      kind: ResearchFindingKind
      direction: ResearchEvidenceDirection | None
      dimension: str
      target_ticker: str | None
      statement: str
      evidence_source_hashes: tuple[str, ...]

Rules:

- finding_id non-empty and unique;
- dimension non-empty;
- statement non-empty;
- target_ticker if present must be a work-order target;
- evidence hashes must exist in dossier evidence.

## 56. Finding evidence rules

OBSERVED_SYNTHESIS:

- direction must be non-None;
- at least one evidence hash required;
- every cited evidence record must have is_observed_fact == True.

INFERENCE:

- direction must be non-None;
- at least one evidence hash required;
- may cite observed facts and/or non-observed/model evidence.

UNRESOLVED:

- direction must be None;
- evidence hashes may be empty or non-empty.

A finding kind never changes EvidenceRecord.is_observed_fact.

## 57. Finding scope

If a finding has target_ticker:

- every cited ticker-specific evidence record must either match that ticker or be theme-level evidence.

A company finding cannot cite evidence bound to another target company.

## 58. ResearchExecutionClosure

Define:

    class ResearchExecutionClosure(str, Enum):
        OPEN = "OPEN"
        CLOSED = "CLOSED"

This is explicit caller state.

It is not derived from wall-clock time.

## 59. ResearchDossierStatus

Define:

    class ResearchDossierStatus(str, Enum):
        NOT_STARTED = "NOT_STARTED"
        PARTIAL = "PARTIAL"
        COMPLETE = "COMPLETE"
        BLOCKED_INSUFFICIENT_EVIDENCE = "BLOCKED_INSUFFICIENT_EVIDENCE"

## 60. Completion requirements

A dossier is coverage-complete only when all are true:

- every ResearchRequirement is satisfied;
- total unique independent source_ref count >= work_order.minimum_independent_sources;
- for COMPANY_DEEP_DIVE, every target has a CompanyResearchSubmission;
- for COMPANY_DEEP_DIVE, every target independent-source count >= work_order.minimum_independent_sources_per_company;
- every required company linkage is USABLE.

Findings are not required for mechanical completion.

Research completion means required research coverage was executed, not that the thesis was resolved positively.

## 61. Status derivation

If completion requirements are satisfied:

    COMPLETE

Else if closure == CLOSED:

    BLOCKED_INSUFFICIENT_EVIDENCE

Else if all are empty:

- evidence_bindings;
- company_submissions;
- linkage_submissions;
- findings;

then:

    NOT_STARTED

Else:

    PARTIAL

Caller cannot directly set ResearchDossierStatus.

## 62. COMPLETE may contain contradiction

A COMPLETE dossier may contain:

- contradicting evidence;
- unresolved findings;
- thesis risk;
- negative company evidence.

COMPLETE means execution coverage, not bullishness or approval.

## 63. BLOCKED meaning

BLOCKED_INSUFFICIENT_EVIDENCE means:

    execution was explicitly closed
    while required coverage remained unmet

It does not mean:

    thesis disproven
    trade blocked
    company bad

## 64. ResearchDossier

Define frozen dataclass:

    ResearchDossier
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

## 65. Dossier limitations

Fixed v0.1 limitations:

    (
      "research completion means required coverage, not thesis correctness",
      "allocation tier does not prove research execution without a dossier",
      "provider retrieval and extraction occur outside this module",
      "theme package exact historical bytes are not recoverable from ReplayCycleResult alone",
      "research dossier does not grant trading permission",
    )

These are included in dossier_hash.

## 66. Contradictions-present derivation

contradictions_present is True if any is true:

- any ResearchEvidenceBinding.direction == CONTRADICTING;
- any non-UNRESOLVED finding.direction == CONTRADICTING.

This is descriptive.

It does not alter completion status.

## 67. Unresolved-present derivation

unresolved_present is True if any finding.kind == UNRESOLVED.

This is descriptive.

It does not automatically make status PARTIAL when all mechanical coverage requirements are satisfied.

## 68. Dossier input hash

Compute input_hash from semantic execution inputs:

- work_order_hash;
- evidence_as_of;
- closure;
- validated ResearchEvidenceBinding payloads;
- CompanyResearchSubmission payloads;
- CompanyLinkageSubmission payloads;
- ResearchFinding payloads.

Canonicalize all collection order before hashing.

## 69. Dossier hash

Compute dossier_hash from the complete ResearchDossier semantic payload with dossier_hash omitted.

No self-reference.

## 70. Canonical ordering

Work-order targets:

    ticker

Requirements:

    (scope.value, target_ticker or "", dimension)

Evidence bindings:

    (
      evidence.source_hash,
      target_ticker or "",
      direction.value,
      dimensions
    )

Company assessments:

    ticker

Findings:

    finding_id

Satisfied/unsatisfied requirements:

    requirement ordering

Input order must not affect identity.

## 71. Evidence direction conflicts are preserved

Two independent sources may support opposite directions.

Increment 8 does not collapse them into a single thesis score.

The dossier exposes:

    contradictions_present = True

and retains each evidence binding.

## 72. Evidence source priority

Existing SOURCE_PRIORITY may be exposed only as metadata through EvidenceRecord.source_priority.

Increment 8 does not combine source priorities into a weighted evidence score.

## 73. Model evidence

Evidence with:

    source_type == "radar_model_output"
    or
    is_observed_fact == False

may be included.

It never becomes observed fact merely because it appears in a dossier.

Independent-source status is explicit in ResearchEvidenceBinding and is not inferred from model/source type.

## 74. Provider-neutral boundary

External systems may later construct valid EvidenceRecord values from:

- SEC;
- IR;
- official macro;
- reputable reporting;
- market data.

Increment 8 does not know or care which provider performed retrieval.

Its only concern is deterministic validation and execution semantics.

## 75. No raw secret handling

Research execution inputs must not contain:

- credentials;
- API tokens;
- brokerage account data;
- personal holdings;
- confidential employer data.

The module does not provide secret redaction.

## 76. First work-order acceptance: ordinary full company research

Construct a registered theme replay where:

    RoutingIntent == ORDINARY_FULL_RESEARCH
    ResearchTier == FULL_DECISION_RESEARCH

Supply matching ThemePackage and explicit effective target tickers.

Required:

- authorization == ALLOCATED_FULL;
- research_mode == COMPANY_DEEP_DIVE;
- targets match explicit effective subset;
- adapter-specific requirements generated per company;
- linkage requirement generated per company;
- deterministic work_order_hash.

## 77. Forced-full acceptance

Construct:

    RoutingIntent == FORCED_FULL_REVIEW

Build THEME_REASSESSMENT.

Required:

- authorization == ALLOCATED_FULL;
- contradiction questions populated;
- target list empty;
- theme-level requirements generated.

Also permit COMPANY_DEEP_DIVE when registered package + explicit targets are supplied.

## 78. Unregistered forced-review acceptance

Construct:

    RoutingIntent == FORCED_REVIEW_UNREGISTERED
    source_registered == False
    source_tier == SCAN_ONLY

Build THEME_REASSESSMENT.

Required:

- authorization == UNREGISTERED_FORCED_REVIEW;
- source_allocated_tier remains SCAN_ONLY;
- no package;
- no company targets;
- no claim of FULL allocation.

## 79. Capacity-missed rejection acceptance

Construct:

    RoutingIntent == FORCED_REVIEW_CAPACITY_MISSED

Attempt any work order.

Required:

    ValueError("routing state is not executable in research v0.1")

This preserves research-budget capacity semantics.

## 80. Target-effectivity acceptance

For COMPANY_DEEP_DIVE reject:

- unknown ticker;
- future candidate;
- expired candidate;
- duplicate ticker;
- retired/non-effective candidate.

Do not silently substitute another candidate.

## 81. Evidence-hash acceptance

Starting from a valid EvidenceRecord:

- tamper payload;
- preserve old source_hash.

build_research_dossier must reject it.

Also reject missing/malformed source_hash.

## 82. Future-evidence acceptance

Reject evidence whose:

- observed_at;
- market_asof;
- retrieved_at

exceeds evidence_as_of.

No lookahead is silently accepted.

## 83. Company raw-fact provenance acceptance

For a valid company submission:

    raw_facts = {"revenue_growth": 0.2}

at least one cited evidence payload must contain:

    {"revenue_growth": 0.2}

Change raw_facts to 0.3 without changing evidence.

Required:

    ValueError("company raw fact is unsupported by cited evidence")

## 84. Adapter-specific acceptance

DataCenter / industrials work order:

- dispatch IndustrialsInfrastructureAdapter;
- normalized evidence preserves industrial metrics.

Genomics / biotech work order:

- dispatch BiotechClinicalAdapter;
- normalized evidence preserves clinical/regulatory/runway fields.

Do not compare them on one company score.

## 85. Linkage acceptance

For required company linkage:

### usable

A valid hierarchical status "ok" or non-null simple correlation/beta/r2 satisfies the linkage requirement.

### coverage pending

Does not satisfy.

### circularity warning

Does not satisfy and adds caution.

## 86. Partial dossier acceptance

OPEN execution with:

- some evidence;
- unmet requirements.

Required:

    status == PARTIAL

Unsatisfied requirements remain explicit.

## 87. Not-started acceptance

OPEN execution with no:

- evidence bindings;
- company submissions;
- linkage submissions;
- findings.

Required:

    status == NOT_STARTED

## 88. Blocked acceptance

CLOSED execution with unmet requirements:

    status == BLOCKED_INSUFFICIENT_EVIDENCE

No bullish/bearish interpretation is attached.

## 89. Complete acceptance

When all requirements and independent-source minima are satisfied:

    status == COMPLETE

This remains true even if:

    contradictions_present == True
    unresolved_present == True

Coverage completion is separate from conclusion direction.

## 90. Finding provenance acceptance

OBSERVED_SYNTHESIS citing a non-observed/model-only EvidenceRecord:

    reject

INFERENCE citing the same evidence:

    allowed

UNRESOLVED with no evidence:

    allowed

## 91. Dossier determinism acceptance

Reverse:

- evidence binding order;
- company submission order;
- linkage submission order;
- finding order.

Required:

    identical ResearchDossier
    identical input_hash
    identical dossier_hash

## 92. Work-order determinism acceptance

Reverse target_tickers input order.

Required:

    identical ResearchWorkOrder
    identical work_order_hash

Change one target:

    different work_order_hash

## 93. No mutation

Building WorkOrder or Dossier must not mutate:

- ReplayArchiveRecord;
- ThemePackage;
- EvidenceRecord;
- raw_facts mappings;
- linkage results;
- findings/submissions.

Copy mutable mappings before storage.

## 94. Purity audit

research_execution.py must not import/call:

    pathlib
    os
    json file I/O
    requests
    urllib
    httpx
    yfinance
    alpaca
    polygon
    subprocess
    socket
    datetime.now
    time.time
    random
    uuid
    make_evidence
    assess_tape_state
    route_playbooks
    compile_decision
    write_immutable_json

The module may use datetime parsing with explicit input timestamps.

## 95. Proposed public interfaces

Export:

    ResearchMode
    ResearchAuthorization
    ResearchRequirementScope
    ResearchRequirement
    ResearchTarget
    ResearchWorkOrderPolicy
    ResearchWorkOrder
    ResearchEvidenceDirection
    ResearchEvidenceBinding
    CompanyResearchSubmission
    CompanyLinkageSubmission
    CompanyLinkageStatus
    CompanyResearchAssessment
    ResearchFindingKind
    ResearchFinding
    ResearchExecutionClosure
    ResearchDossierStatus
    ResearchDossier
    build_research_work_order
    build_research_dossier

## 96. Proposed files

Create:

    src/decision_lab/research_execution.py

Create:

    tests/test_research_execution.py

Modify for exports only:

    src/decision_lab/__init__.py

Do not modify behavior in:

    src/decision_lab/replay.py
    src/decision_lab/replay_archive.py
    src/decision_lab/replay_cohort.py
    src/decision_lab/scanner.py
    src/decision_lab/research_budget.py
    src/decision_lab/market_observation.py
    src/decision_lab/evidence.py
    src/decision_lab/adapters.py
    src/decision_lab/linkage.py
    src/decision_lab/hierarchical.py
    src/decision_lab/tape.py
    src/decision_lab/playbooks.py
    src/decision_lab/decision.py
    src/decision_lab/outcomes.py
    src/decision_lab/themes.py
    src/decision_lab/universe.py
    src/decision_lab/ledger.py

If implementation requires changing those semantics, stop and upgrade scope.

## 97. Deferred work

Deliberately deferred:

- live evidence retrieval;
- SEC/IR/news provider integrations;
- automatic extraction;
- LLM research execution;
- typed filesystem archive for WorkOrder/Dossier;
- research-attempt history/versioning;
- human-review signatures;
- evidence licensing policy;
- decision-readiness gate;
- Tape/Playbook integration;
- trade Decision Object;
- value-of-research evaluation;
- research-cost accounting;
- company ranking.

## 98. Completion criterion

Increment 8 is complete when the system can deterministically transform:

    valid historical replay routing
      -> explicit ResearchWorkOrder
      -> frozen, hash-valid research evidence
      -> structured company normalization/linkage where applicable
      -> ResearchDossier

while preserving all of these distinctions:

- allocation != execution;
- completion != thesis correctness;
- contradiction != incompleteness;
- unresolved questions != execution failure;
- unregistered forced review != FULL allocation;
- capacity-missed review != executable authorization;
- linkage coverage/circularity != usable linkage;
- model/inference evidence != observed fact;
- research completion != trading permission;

with:

- no provider/network dependency;
- no ambient time;
- no company score;
- no Tape/Playbook/Decision integration;
- deterministic semantic hashes;
- all existing tests green;
- changed-files Ruff green.


## 99. Company requirement field-name contract

For COMPANY_EVIDENCE requirements, dimension names are intentionally the exact public dataclass field names produced by the selected adapter.

Before snapshot conversion, evaluate coverage against the adapter output:

- require hasattr(normalized_evidence, dimension);
- read the attribute;
- require it is not None.

After conversion, the same dimension must appear in NormalizedCompanySnapshot.fields.

If a policy dimension is not a valid normalized-evidence field for the selected adapter:

    raise ValueError("company requirement dimension is unsupported by adapter")

This prevents policy/schema drift from silently making completion impossible or falsely complete.

## 100. Evidence-binding canonicalization

build_research_dossier converts ResearchEvidenceInput into canonical ResearchEvidenceBinding snapshots rather than retaining caller objects.

For each input:

- EvidenceRecord is validated;
- FrozenResearchEvidence is created;
- dimensions are stripped only of surrounding whitespace, must remain non-empty, deduplicated, and sorted;
- target_ticker is uppercased when present.

Two inputs with the same evidence.source_hash are rejected rather than merged.

Mutating the caller's original EvidenceRecord.payload after dossier construction must not change the dossier or its hashes.

## 101. Work-order validation before dossier execution

build_research_dossier must independently validate work_order_hash by recomputing the complete work-order semantic payload.

A manually constructed or tampered ResearchWorkOrder is rejected:

    ValueError("invalid research work order")

The dossier builder does not trust a hash-shaped string merely because it is present.


## 102. Generic-adapter rejection acceptance

Construct a registered FULL research source with ThemePackage.evidence_adapter == "generic".

Attempt COMPANY_DEEP_DIVE.

Required:

    ValueError("generic adapter is not eligible for company deep dive")

Do not generate an impossible work order whose normalized evidence requirements can never be satisfied.


## 103. Immutable nested-state acceptance

After building a dossier:

1. mutate the original EvidenceRecord.payload mapping;
2. mutate the original CompanyResearchSubmission.raw_facts mapping;
3. mutate the original HierarchicalLinkageResult.coefficients mapping.

Required:

- ResearchDossier remains exactly equal to its pre-mutation value;
- dossier_hash remains unchanged;
- stored FrozenResearchEvidence, NormalizedCompanySnapshot, and HierarchicalLinkageSnapshot remain unchanged.

This proves frozen dataclass semantics are not undermined by caller-owned mutable mappings.

## 104. ResearchEvidenceInput independence acceptance

Reject:

- radar_model_output with independent=True;
- any EvidenceRecord with is_observed_fact=False and independent=True.

Allow the same records with independent=False.

Independence is explicit but cannot elevate model/inferred evidence into independent observed evidence.
