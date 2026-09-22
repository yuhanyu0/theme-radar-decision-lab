# Increment 9 — Immutable Research Execution Archive Design

Date: 2026-09-22
Status: approved in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: feature/research-execution-archive

## 1. Purpose

Persist the epistemic process introduced by Increment 8 as immutable, content-addressed historical records.

Target chain:

    ReplayArchiveRecord
      -> ResearchWorkOrderArchiveRecord
      -> ResearchDossierArchiveRecord D0
      -> ResearchDossierArchiveRecord D1
      -> ResearchDossierArchiveRecord D2

The archive must preserve:

- allocation lineage;
- research authorization lineage;
- research execution snapshots;
- explicit optional parent links between dossier snapshots;
- append-only history.

Increment 9 records history. It does not evaluate progression.

## 2. Scientific role

Increment 8 established:

    allocation
      != execution
      != research completion
      != trading permission

Increment 9 makes those distinctions historical rather than transient.

The archive must make it possible to answer later:

- what research task existed at a historical source cycle;
- what its exact deterministic WorkOrder was;
- what Dossier snapshots were produced for that WorkOrder;
- which Dossier snapshot explicitly followed which prior snapshot;
- whether those records have remained cryptographically intact.

## 3. Selected architecture

Add one module:

    src/decision_lab/research_execution_archive.py

It archives two immutable record types:

    ResearchWorkOrderArchiveRecord
    ResearchDossierArchiveRecord

The module owns:

- typed archive records;
- semantic record hashing;
- strict typed JSON decoding;
- path construction;
- read/verify;
- append-only write semantics;
- public/private destination policy;
- WorkOrder-to-replay and Dossier-to-WorkOrder lineage checks;
- optional explicit parent reference validation.

It does not own:

- research progression evaluation;
- archive graph scanning;
- fork/orphan resolution;
- indexing;
- network retrieval;
- research execution semantics.

## 4. Explicit non-goals

Increment 9 does not add:

- ResearchProgression evaluation;
- time-to-closure metrics;
- requirement-resolution metrics;
- Decision Readiness;
- Tape assessment;
- playbook routing;
- Decision Object compilation;
- price-outcome scoring;
- provider retrieval;
- SEC/IR/news fetching;
- LLM research execution;
- archive directory scanning;
- archive index;
- manifest;
- SQLite;
- fork resolution;
- orphan resolution;
- canonical branch selection;
- research-value estimation;
- research-cost accounting;
- automatic privacy classification.

## 5. Archive root

Canonical public archive root:

    recomputed/research_execution

Subdirectories:

    work_orders/
    dossiers/

A caller supplies archive_root as the root ending in:

    recomputed/research_execution

## 6. WorkOrder archive path

Canonical WorkOrder path:

    <archive_root>/
      work_orders/
        <source-cycle-UTC-date>/
          <work_order_hash>.json

Example:

    recomputed/research_execution/
      work_orders/
        2026-09-19/
          abcdef....json

The date comes from ResearchWorkOrder.source_cycle_as_of normalized to UTC date.

## 7. Dossier archive path

Canonical Dossier path:

    <archive_root>/
      dossiers/
        <source-cycle-UTC-date>/
          <work_order_hash>/
            <archive_record_hash>.json

All dossier snapshots for one WorkOrder remain grouped under the source replay cycle and WorkOrder hash.

The path does not use the dossier evidence_as_of date.

## 8. Why source-cycle grouping

For a WorkOrder created from a source cycle at t0, all later execution snapshots belong to that original epistemic task.

Therefore:

    t0 = source_cycle_as_of

is the grouping identity.

A Dossier produced days later still belongs under:

    <t0 UTC date>/<work_order_hash>/

This supports later time-to-closure analysis without moving historical files.

## 9. ArchiveDestinationVisibility

Define:

    class ResearchArchiveDestinationVisibility(str, Enum):
        PUBLIC = "public"
        PRIVATE = "private"

This is separate from Replay archive naming.

## 10. Public destination policy

PUBLIC writes require:

    public_safe is True

using literal identity:

    public_safe is True

Values such as:

    1
    "yes"

do not count.

If false or non-literal:

    raise PermissionError(
        "public research archive write requires explicit public_safe=True"
    )

## 11. Canonical public root

For PUBLIC writes, the resolved archive root must end with:

    recomputed/research_execution

Otherwise:

    raise ValueError(
        "public research archives must use recomputed/research_execution"
    )

## 12. ledger/live prohibition

For both PUBLIC and PRIVATE destinations, any resolved path containing contiguous:

    ledger/live

is rejected.

Error:

    ValueError(
        "research archives may not be written under ledger/live"
    )

## 13. Path resolution

Resolve roots using:

    Path.expanduser().resolve(strict=False)

Containment and policy checks operate on resolved paths.

This prevents symlink aliases from bypassing destination rules.

## 14. Public-safety meaning

public_safe=True is caller affirmation only.

Increment 9 does not inspect Dossier content for:

- secrets;
- personal data;
- licensing restrictions;
- confidential company data;
- employer data.

The archive layer must not claim automatic privacy review.

## 15. WorkOrder archive schema constants

WorkOrder archive constants:

    schema_version = "0.1"
    content_type = "research_work_order"
    producer = "theme-radar-decision-lab/research-execution-archive@0.1"

These values are exact and validated by readers.

## 16. ResearchWorkOrderArchiveRecord

Define frozen dataclass:

    ResearchWorkOrderArchiveRecord
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

## 17. WorkOrder archive builder input

Public builder:

    build_research_work_order_archive_record(
        replay_archive: ReplayArchiveRecord,
        work_order: ResearchWorkOrder,
        *,
        work_order_policy: ResearchWorkOrderPolicy,
    ) -> ResearchWorkOrderArchiveRecord

The caller must provide the replay archive, WorkOrder, and the complete WorkOrder policy used to generate that WorkOrder.

The builder does not accept only hash strings.

The policy is archived because policy identity is part of the historical research regime and cannot be recovered from ResearchWorkOrder.policy_hash alone.

## 18. Replay archive validation

Before building a WorkOrder archive record, rebuild:

    build_replay_archive_record(
        replay_archive.replay_result
    )

and require exact equality with the supplied replay_archive.

If invalid:

    raise ValueError("invalid source replay archive record")

The WorkOrder archive builder must not trust a manually constructed replay archive object.

## 19. WorkOrder and policy validation

The builder must independently validate ResearchWorkOrder semantic integrity and exact policy provenance.

Normalize work_order_policy using the same deterministic Increment-8 policy normalization semantics.

Require:

    canonical_hash(asdict(normalized_policy))
      == work_order.policy_hash

Require:

    normalized_policy.minimum_independent_sources
      == work_order.minimum_independent_sources

    normalized_policy.minimum_independent_sources_per_company
      == work_order.minimum_independent_sources_per_company

Regenerate the expected ResearchRequirement tuple from:

    work_order.research_mode
    work_order.targets
    work_order.evidence_adapter
    normalized_policy

and require exact equality with:

    work_order.requirements

Use a public Increment-8 validation surface if one exists after implementation; otherwise the archive module may call the existing internal deterministic validators/builders.

It must validate more than work_order_hash shape.

A rehashed semantically inconsistent WorkOrder or mismatched policy must fail.

Errors:

    ValueError("invalid research work order")
    ValueError("research work order policy mismatch")

## 20. Replay-to-WorkOrder lineage

Require:

    work_order.source_archive_record_hash
      == replay_archive.archive_record_hash

    work_order.source_replay_result_hash
      == replay_archive.replay_result_hash

    work_order.source_cycle_as_of
      == replay_archive.cycle_as_of

Hash equality is necessary but not sufficient.

The builder must also independently recover the source theme transition from the supplied ReplayArchiveRecord using the same public cohort semantics as Increment 8:

    evaluate_replay_cohort(
        (replay_archive,),
        horizons=(1,),
    )

For work_order.theme_id require exactly one source transition and require:

    transition.routing_intent
      == work_order.source_routing_intent

    transition.source_registered
      == work_order.source_registered

    transition.source_tier
      == work_order.source_allocated_tier

    transition.source_forced_review
      == work_order.source_forced_review

If the theme is absent or any routing provenance differs:

    ValueError("research work order replay lineage mismatch")

This prevents a rehashed, internally self-consistent WorkOrder from falsely claiming a different routing state from the real source replay.

Any mismatch raises:

    ValueError("research work order replay lineage mismatch")

## 21. source_cycle_as_of representation

ResearchWorkOrderArchiveRecord.source_cycle_as_of preserves:

    work_order.source_cycle_as_of

exactly.

Temporal comparisons use normalized UTC instants.

Path date uses normalized UTC date.

## 22. WorkOrder archive semantic hash

archive_record_hash is:

    canonical_hash(
      complete archive semantic payload
      excluding archive_record_hash
    )

The complete normalized WorkOrder policy and nested WorkOrder are included fully.

No archived_at wall-clock timestamp is included.

## 23. Why no archived_at

Filesystem mtime is operational metadata.

It is not scientific identity.

Two identical archive records created at different wall-clock times must have identical archive_record_hash.

## 24. Dossier archive schema constants

Dossier archive constants:

    schema_version = "0.1"
    content_type = "research_dossier"
    producer = "theme-radar-decision-lab/research-execution-archive@0.1"

## 25. ResearchDossierArchiveRecord

Define frozen dataclass:

    ResearchDossierArchiveRecord
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

## 26. Why embed the WorkOrder archive record

A Dossier archive embeds the complete WorkOrder archive record.

This makes one Dossier archive file sufficient to validate:

    Dossier
      -> WorkOrder
      -> replay archive hash commitment

without separately loading the WorkOrder file.

It does not prove that the replay archive file currently exists on disk.

## 27. Dossier archive builder

Public builder:

    build_research_dossier_archive_record(
        work_order_archive: ResearchWorkOrderArchiveRecord,
        dossier: ResearchDossier,
        *,
        prior_dossier_archive: ResearchDossierArchiveRecord | None = None,
    ) -> ResearchDossierArchiveRecord

The optional parent is an actual typed record, not a raw hash string.

## 28. Embedded WorkOrder archive validation

Before accepting a WorkOrder archive into a Dossier archive, independently validate:

- WorkOrder archive constants;
- work_order_hash;
- nested WorkOrder semantic hash;
- archive_record_hash;
- internal top-level/nested hash equality;
- source-cycle equality.

A malformed/tampered embedded WorkOrder archive is rejected.

## 29. Dossier semantic validation limitation

ResearchDossier does not retain every raw execution input used to build:

    input_hash

Examples not fully retained include:

- original CompanyResearchSubmission raw-fact input object;
- original CompanyLinkageSubmission input object;
- original EvidenceRecord payload content.

Therefore standalone archive validation cannot independently rerun build_research_dossier from raw inputs and cannot independently recompute the semantic origin of ResearchDossier.input_hash.

The reader must:

- require dossier.input_hash is a lowercase 64-character SHA-256 hex string;
- preserve it exactly;
- verify that dossier_hash commits to it as part of the complete stored Dossier payload.

The reader must not claim that dossier.input_hash itself was independently regenerated from original execution inputs.

This limitation is explicit.

## 30. What Dossier validation can recompute

The archive validator must recompute and verify from the stored Dossier:

- dossier_hash;
- work_order_hash relation;
- source_archive_record_hash relation;
- source_cycle_as_of relation;
- theme_id relation;
- research_mode relation;
- evidence_as_of validity;
- satisfied/unsatisfied requirement partition;
- independent_source_count;
- contradictions_present;
- unresolved_present;
- company-assessment target coverage;
- ResearchDossier.status from the stored Dossier plus embedded WorkOrder.

The status is fully recoverable because the stored Dossier exposes:

- evidence_bindings;
- findings;
- per-target normalized_evidence presence;
- per-target linkage status;
- independent-source counts;
- closure;
- satisfied/unsatisfied requirements.

This archive-level recomputation does not require the original raw submission objects.

It must not claim raw-evidence re-verification.

## 31. Dossier-to-WorkOrder lineage

Require:

    dossier.work_order_hash
      == work_order_archive.work_order_hash

    dossier.source_archive_record_hash
      == work_order_archive.source_replay_archive_record_hash

    normalized(dossier.source_cycle_as_of)
      == normalized(work_order_archive.source_cycle_as_of)

    dossier.theme_id
      == work_order_archive.work_order.theme_id

    dossier.research_mode
      == work_order_archive.work_order.research_mode

Mismatch:

    ValueError("research dossier work-order lineage mismatch")

## 32. evidence_as_of relation

Require:

    normalized(dossier.evidence_as_of)
      >= normalized(dossier.source_cycle_as_of)

This repeats the Increment-8 temporal invariant at archive validation.

## 33. Parentless dossier snapshot

The first archived snapshot for a WorkOrder may use:

    prior_dossier_archive_record_hash = None

No archive scan is performed to prove that it is globally the first snapshot.

This is only a local record claim.

## 34. Parent-linked dossier snapshot

If prior_dossier_archive is supplied:

- validate the parent archive record completely;
- require same work_order_hash;
- require same source cycle;
- require same theme_id;
- require same research_mode;
- require current evidence_as_of strictly later than parent evidence_as_of;
- set prior_dossier_archive_record_hash to parent.archive_record_hash.

## 35. Strictly later parent time

For a parent-child link:

    current_evidence_as_of
      > prior_evidence_as_of

Equality is rejected.

Error:

    ValueError("research dossier parent must be strictly earlier")

This avoids two distinct child snapshots claiming sequential progression at the same normalized instant.

## 36. No monotonic evidence-set requirement

Increment 9 does not require:

    child evidence set superset of parent evidence set

or:

    child satisfied requirements superset of parent

or:

    status monotonicity

because later research may:

- retract evidence;
- invalidate linkage;
- revise findings;
- lose sufficiency;
- close with insufficient evidence.

The archive records chronology, not semantic monotonicity.

## 37. COMPLETE-to-PARTIAL is allowed

A sequence such as:

    COMPLETE
      -> PARTIAL

is archive-valid if the later snapshot is otherwise valid and strictly later.

Increment 10 may interpret this as loss of closure/sufficiency.

Increment 9 must not reject it.

## 38. Forks are allowed

Two different children may point to the same prior_dossier_archive_record_hash.

This forms a fork.

Increment 9 does not reject or resolve forks.

Fork analysis belongs to Increment 10.

## 39. Orphan references

A Dossier archive reader may encounter:

    prior_dossier_archive_record_hash = "<valid hash>"

without access to the parent file.

Standalone read/verify does not scan storage for the parent.

Therefore the record may be locally valid but globally orphaned.

Orphan detection belongs to Increment 10.

## 40. Why parent references are explicit

Path or modification-time order is not a scientific progression relation.

Explicit parent hashes distinguish:

    happened later

from:

    explicitly derived as the next research snapshot

This enables later graph-based evaluation.

## 41. Dossier archive semantic hash

archive_record_hash includes:

- archive constants;
- source_cycle_as_of;
- evidence_as_of;
- complete embedded WorkOrder archive;
- prior_dossier_archive_record_hash;
- dossier_hash;
- complete ResearchDossier.

Exclude only:

    archive_record_hash

before hashing.

## 42. Hash format

All SHA-256 values stored as archive/hash identities must be:

- str;
- lowercase;
- exactly 64 hexadecimal characters.

Reject malformed values.

## 43. WorkOrder archive reader

Public:

    read_research_work_order_archive(
        path: str | Path
    ) -> ResearchWorkOrderArchiveRecord

It performs:

- JSON parse;
- non-finite constant rejection;
- exact field-set validation;
- typed recursive decode;
- nested WorkOrder reconstruction;
- semantic validation;
- archive hash validation;
- filename validation;
- cycle-directory validation.

## 44. Dossier archive reader

Public:

    read_research_dossier_archive(
        path: str | Path
    ) -> ResearchDossierArchiveRecord

It performs:

- JSON parse;
- non-finite constant rejection;
- exact field-set validation;
- typed recursive decode;
- nested WorkOrder archive reconstruction;
- ResearchDossier reconstruction;
- Dossier/WorkOrder lineage validation;
- dossier hash validation;
- archive hash validation;
- filename validation;
- path work_order_hash validation;
- source-cycle directory validation.

It does not load parent files.

## 45. WorkOrder filename rule

WorkOrder archive filename must be:

    <work_order_hash>.json

Mismatch:

    ValueError("research work-order archive filename mismatch")

## 46. Dossier filename rule

Dossier archive filename must be:

    <archive_record_hash>.json

not dossier_hash.

Reason:

    prior_dossier_archive_record_hash

is part of archive semantics but not part of ResearchDossier.dossier_hash. Two archive records may therefore contain the same Dossier snapshot while committing to different parent lineage. Using dossier_hash as the filename would create a false path collision.

Mismatch:

    ValueError("research dossier archive filename mismatch")

## 47. Dossier parent-directory rule

For Dossier archive path:

    .../<source-cycle-date>/<work_order_hash>/<archive_record_hash>.json

The immediate parent directory must equal:

    work_order_hash

Mismatch:

    ValueError("research dossier work-order directory mismatch")

## 48. Cycle-directory rule

The source-cycle directory must equal the UTC date derived from:

    source_cycle_as_of

Mismatch:

    ValueError("research archive cycle directory mismatch")

## 49. Strict JSON decoding

Readers use exact field sets at every typed level.

Unknown fields are rejected.

Missing fields are rejected.

Primitive types are strict:

- bool is not int;
- numeric fields reject bool;
- tuple/list fields require JSON arrays;
- enum fields require valid enum strings;
- mapping-like historical payloads are not coerced from arbitrary types.

## 50. Non-finite JSON

Readers reject:

    NaN
    Infinity
    -Infinity

using json.loads(parse_constant=...).

No non-standard JSON numeric values are accepted.

## 51. Nested ResearchWorkOrder and policy decoder

Increment 9 must decode ResearchWorkOrderPolicy exactly and normalize/validate it.

Increment 9 must decode ResearchWorkOrder exactly, including:

- ResearchAuthorization;
- ResearchMode;
- ResearchRequirementScope;
- RoutingIntent;
- ResearchTier;
- ResearchTarget tuple;
- ResearchRequirement tuple.

After construction, validate semantic integrity.

## 52. Nested ResearchDossier decoder

Decode ResearchDossier exactly, including:

- ResearchExecutionClosure;
- ResearchDossierStatus;
- ResearchEvidenceDirection;
- ResearchFindingKind;
- CompanyLinkageStatus;
- all immutable snapshot dataclasses;
- ResearchRequirement tuples;
- ResearchFinding tuples;
- linkage snapshots/results.

No caller-owned mutable object survives decoding.

## 53. Linkage decoding

LinkageResult is decoded as typed frozen dataclass.

HierarchicalLinkageSnapshot coefficients decode as:

    tuple[tuple[str, float], ...]

All numeric fields must be finite when non-None.

## 54. FrozenResearchEvidence decoding

FrozenResearchEvidence contains only immutable scalar/hash metadata.

The original EvidenceRecord payload is not restored.

payload_hash remains a commitment only.

## 55. Evidence payload limitation string

Increment 9 must not add or imply raw evidence recovery.

It relies on Increment-8 Dossier limitation:

    "evidence payload content is committed by hash but not embedded in the dossier"

Archive verification preserves that boundary.

## 56. WorkOrder archive verification helper

Public:

    verify_research_work_order_archive(
        path: str | Path
    ) -> bool

Return False for:

- missing file;
- malformed JSON;
- type errors;
- value errors;
- hash mismatch;
- path mismatch.

Do not swallow PermissionError.

## 57. Dossier archive verification helper

Public:

    verify_research_dossier_archive(
        path: str | Path
    ) -> bool

Same failure policy as WorkOrder verification.

Do not scan for parent.

## 58. WorkOrder path helper

Public:

    research_work_order_archive_path(
        record: ResearchWorkOrderArchiveRecord,
        archive_root: str | Path,
    ) -> Path

It does not create directories.

## 59. Dossier path helper

Public:

    research_dossier_archive_path(
        record: ResearchDossierArchiveRecord,
        archive_root: str | Path,
    ) -> Path

It does not create directories.

## 60. WorkOrder write helper

Public:

    write_research_work_order_archive(
        record,
        archive_root,
        *,
        destination_visibility,
        public_safe=False,
    ) -> ResearchArchiveWriteResult

## 61. Dossier write helper

Public:

    write_research_dossier_archive(
        record,
        archive_root,
        *,
        destination_visibility,
        public_safe=False,
    ) -> ResearchArchiveWriteResult

Both use identical append-only semantics.

## 62. ResearchArchiveWriteResult

Define frozen dataclass:

    ResearchArchiveWriteResult
      path: Path
      created: bool
      content_hash: str
      archive_record_hash: str

For WorkOrder:

    content_hash = work_order_hash

For Dossier:

    content_hash = dossier_hash

## 63. Deterministic JSON serialization

Write JSON as:

    UTF-8
    ensure_ascii=False
    sort_keys=True
    indent=2
    allow_nan=False
    trailing newline

Serialization bytes are deterministic for the same archive record.

## 64. Exclusive file creation

Use:

    os.O_WRONLY | os.O_CREAT | os.O_EXCL

No overwrite mode.

## 65. Idempotent identical write

If target file already exists:

1. reject symlink target as conflict;
2. read and fully validate existing archive record;
3. compare complete semantic archive payload;
4. if exact equality:

       created=False

5. otherwise:

       raise FileExistsError("research archive path conflict")

## 66. Invalid existing file is conflict

If an existing target file is:

- malformed JSON;
- invalid hash;
- wrong schema;
- wrong path identity;
- wrong nested lineage;

the writer must not replace it.

Raise:

    FileExistsError("research archive path conflict")

## 67. Partial write cleanup

If a newly created file fails during write:

- delete only that newly created path;
- re-raise the original exception.

Never delete a pre-existing file.

## 68. Directory creation

Writer may create required parent directories after destination-policy validation.

Path helpers themselves do not create directories.

## 69. Symlink escape defense

Before and after parent-directory creation, require resolved target directory remains under the resolved archive root.

A source-cycle directory or work-order directory symlink that escapes the root is rejected.

No bytes are written outside the resolved root.

## 70. Existing archive-file symlink

If the final archive path already exists as a symlink:

    FileExistsError("research archive path conflict")

Do not follow it for idempotence.

## 71. PUBLIC WorkOrder path

For PUBLIC:

    <resolved_root>/work_orders/...

where resolved_root ends:

    recomputed/research_execution

No alternate public tree is accepted.

## 72. PUBLIC Dossier path

For PUBLIC:

    <resolved_root>/dossiers/...

with the same canonical root requirement.

## 73. PRIVATE destination

PRIVATE destinations may use any resolved root except paths under:

    ledger/live

public_safe is ignored for authorization purposes.

## 74. Reader path safety

Readers validate semantic path identity.

They do not apply PUBLIC/PRIVATE destination policy because reading may occur from arbitrary copied locations.

However path components required by the record schema remain validated.

## 75. WorkOrder standalone integrity boundary

A valid WorkOrder archive proves:

- the nested WorkOrder is internally semantically valid;
- it cryptographically commits to one source replay archive hash/result hash;
- at creation time the builder received a matching valid ReplayArchiveRecord if created through the builder.

A later standalone reader cannot prove the source Replay archive file still exists.

## 76. Dossier standalone integrity boundary

A valid Dossier archive proves:

- the nested Dossier is structurally and semantically self-consistent to the recoverable extent;
- it matches the embedded WorkOrder archive;
- its parent hash, if present, is well formed;
- at creation time the builder received a valid matching parent record if a parent was supplied.

A later standalone reader cannot prove:

- parent file existence;
- parent uniqueness;
- absence of forks;
- raw evidence payload correctness.

## 77. No archive scan in builders

Builders receive explicit typed inputs.

They do not search archive directories for:

- existing WorkOrder records;
- previous Dossier records;
- parent candidates;
- latest snapshot.

The caller selects the explicit parent.

## 78. No implicit latest-parent behavior

Do not implement:

    "find latest dossier for this WorkOrder"

inside Increment 9.

This would introduce hidden graph semantics and filesystem dependence.

## 79. No mtime ordering

Filesystem modification time must never determine:

- parent;
- chronology;
- canonical progression;
- latest Dossier.

Only explicit evidence_as_of and parent hash are semantic.

## 80. No status ordering

Increment 9 does not rank:

    NOT_STARTED
    PARTIAL
    COMPLETE
    BLOCKED_INSUFFICIENT_EVIDENCE

for progression purposes.

No monotonic transition rule exists here.

## 81. No requirement-resolution metrics

Increment 9 does not compute:

    newly_satisfied_requirements
    newly_unsatisfied_requirements
    requirement_delta
    closure_velocity

Those belong to Increment 10.

## 82. No time-to-closure metrics

Increment 9 stores enough timestamps for later calculation but does not compute:

    time_to_first_evidence
    time_to_first_independent_evidence
    time_to_linkage
    time_to_complete

## 83. No value-of-research metric

Do not add:

    research_value
    information_gain
    decision_gain
    utility_gain
    ROI
    accuracy
    performance_score

to archive records.

## 84. WorkOrder build acceptance

Given a valid ReplayArchiveRecord and valid matching ResearchWorkOrder:

    build_research_work_order_archive_record(...)

returns a deterministic record.

Rebuilding with identical inputs returns exact equality.

archive_record_hash is lowercase 64-char SHA-256.

## 85. WorkOrder replay-lineage tamper acceptance

Take a valid WorkOrder and alter:

    source_archive_record_hash

then recompute a valid work_order_hash.

The WorkOrder archive builder must still reject against the supplied ReplayArchiveRecord:

    ValueError("research work order replay lineage mismatch")

Hash self-consistency alone is insufficient.

## 86. Invalid replay archive acceptance

Take a ReplayArchiveRecord and alter a nested replay value without a matching archive_record_hash.

WorkOrder archive building rejects:

    ValueError("invalid source replay archive record")

## 87. WorkOrder path acceptance

For source cycle:

    2026-09-19

and work_order_hash H:

    research_work_order_archive_path(...)

ends:

    work_orders/2026-09-19/H.json

No filesystem creation occurs.

## 88. WorkOrder round-trip acceptance

Build -> write -> read:

    loaded == original_record

verify helper returns True.

Second identical write:

    created=False

## 89. WorkOrder tamper acceptance

Tamper any of:

- nested WorkOrder requirement;
- work_order_hash;
- replay archive hash;
- archive_record_hash;
- schema/content_type/producer.

Reader and verifier fail closed.

## 90. WorkOrder wrong filename acceptance

Store valid bytes under a different filename.

Reader rejects:

    research work-order archive filename mismatch

## 91. Dossier root acceptance

Build first Dossier archive with:

    prior_dossier_archive=None

Result:

    prior_dossier_archive_record_hash is None

and lineage matches embedded WorkOrder archive.

## 92. Dossier child acceptance

Build child using prior Dossier archive.

Require:

    child.prior_dossier_archive_record_hash
      == parent.archive_record_hash

and:

    child evidence_as_of > parent evidence_as_of

## 93. Same-time child rejection

If normalized child evidence_as_of equals parent evidence_as_of:

    ValueError("research dossier parent must be strictly earlier")

Equivalent timezone spellings count as equal.

## 94. Earlier child rejection

If child evidence_as_of < parent evidence_as_of:

same error:

    research dossier parent must be strictly earlier

## 95. Cross-WorkOrder parent rejection

Parent and child WorkOrder hashes differ:

    ValueError("research dossier parent work order mismatch")

## 96. Cross-theme/research-mode parent rejection

Even if a malicious record reuses hash-shaped values, parent validation requires embedded WorkOrder identity closure.

Reject inconsistent parent lineage.

## 97. Non-monotonic status acceptance

A valid parent COMPLETE and valid later child PARTIAL are accepted.

Increment 9 must not impose status monotonicity.

## 98. Non-monotonic evidence acceptance

A child with fewer evidence bindings than its parent is allowed when otherwise valid.

This preserves retraction/revision semantics.

## 99. Fork acceptance

Build two different child Dossiers from the same parent:

    D2A.parent = D1.hash
    D2B.parent = D1.hash

Both records are individually valid.

No canonical child is selected.

## 100. Dossier path acceptance

For source cycle date D, WorkOrder hash W, archive-record hash A:

    research_dossier_archive_path(...)

ends:

    dossiers/D/W/A.json

## 101. Dossier round-trip acceptance

Build -> write -> read returns exact typed equality.

verify returns True.

Second identical write:

    created=False

## 102. Dossier wrong work-order directory acceptance

Place valid dossier file under:

    dossiers/D/OTHER/A.json

Reader rejects:

    research dossier work-order directory mismatch

## 103. Dossier wrong filename acceptance

Place under correct WorkOrder directory but a filename not equal to archive_record_hash:

    research dossier archive filename mismatch

## 104. Dossier cycle-directory acceptance

Wrong source-cycle directory:

    research archive cycle directory mismatch

## 105. Parent nonexistence standalone acceptance

Construct valid child archive with a parent hash through the builder.

Copy only the child file to a different location preserving required semantic path.

Standalone read still succeeds without searching for parent.

This confirms orphan detection is deferred.

## 106. WorkOrder symlink escape acceptance

A source-cycle directory symlink pointing outside archive root is rejected before write.

No external file is created.

## 107. Dossier work-order-directory symlink escape acceptance

A WorkOrder-hash directory symlink pointing outside root is rejected.

No external file is created.

## 108. Existing-file symlink acceptance

Existing final-file symlink is treated as conflict.

Never resolve it as idempotent content.

## 109. Partial write cleanup acceptance

Simulate writer failure after exclusive file creation.

The new partial file is removed.

Pre-existing records are never removed.

## 110. PUBLIC safety acceptance

PUBLIC write with:

    public_safe=False
    public_safe=1
    public_safe="yes"

all reject before directory/file creation.

Only literal True authorizes.

## 111. Canonical-root acceptance

PUBLIC root such as:

    reports/research_execution

is rejected.

A symlink resolving to a noncanonical root is also rejected.

## 112. ledger/live acceptance

PUBLIC and PRIVATE writes under:

    ledger/live

or a symlink resolving under it are rejected.

## 113. Deterministic JSON acceptance

Writing identical records to two PRIVATE roots produces identical file bytes.

Filesystem mtime changes do not affect read record or hash identity.

## 114. Malformed JSON acceptance

Malformed JSON:

    verify == False
    read raises

No partial typed object is returned.

## 115. Unknown/missing field acceptance

At every archive and nested typed layer:

- extra field -> reject;
- missing field -> reject.

Do not silently ignore schema drift.

## 116. Non-finite acceptance

Tamper any JSON numeric field to NaN/Infinity.

Reader rejects before accepting typed record.

## 117. Public interfaces

Export:

    ResearchArchiveDestinationVisibility
    ResearchArchiveWriteResult
    ResearchWorkOrderArchiveRecord
    ResearchDossierArchiveRecord
    build_research_work_order_archive_record
    build_research_dossier_archive_record
    research_work_order_archive_path
    research_dossier_archive_path
    read_research_work_order_archive
    read_research_dossier_archive
    verify_research_work_order_archive
    verify_research_dossier_archive
    write_research_work_order_archive
    write_research_dossier_archive

## 118. Proposed files

Create:

    src/decision_lab/research_execution_archive.py

Create:

    tests/test_research_execution_archive.py

Modify exports only:

    src/decision_lab/__init__.py

Do not change behavior in existing modules.

## 119. Forbidden semantic changes

Do not modify behavior in:

    src/decision_lab/research_execution.py
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

If archive implementation requires changing their semantics, stop and upgrade scope.

## 120. Purity boundary

Record builders and path helpers are deterministic and use no ambient clock.

Read/write functions may use filesystem I/O only.

No network imports/calls:

    requests
    urllib
    httpx
    yfinance
    alpaca
    polygon
    socket

No randomness:

    random
    uuid

No ambient semantic timestamps:

    datetime.now
    time.time

## 121. Why no generic write_immutable_json reuse

The archive requires:

- typed decode;
- schema validation;
- path identity validation;
- idempotent identical writes;
- conflict detection;
- symlink containment;
- public/private policy;
- nested lineage verification.

Therefore generic write_immutable_json is insufficient as the archive engine.

## 122. Future Increment 10 input contract

Increment 10 may use:

    Sequence[ResearchDossierArchiveRecord]

or an explicit archive-scanning layer outside Increment 9.

It may then:

- resolve parent references;
- detect roots;
- detect forks;
- detect orphans;
- construct progression chains;
- calculate closure timing;
- calculate requirement transitions.

Increment 9 itself does none of those.

## 123. Key scientific invariant

The archive records:

    epistemic state snapshots
    + explicit local lineage

without interpreting them.

Therefore:

    archived chronology
      != successful research

    parent relation
      != monotonic improvement

    COMPLETE
      != permanent closure

    archive integrity
      != raw evidence truth

## 124. Completion criterion

Increment 9 is complete when the system can deterministically and immutably persist:

    valid ReplayArchiveRecord
      -> valid ResearchWorkOrderArchiveRecord

and:

    valid ResearchWorkOrderArchiveRecord
      + valid ResearchDossier
      + optional valid prior Dossier archive
      -> valid ResearchDossierArchiveRecord

with:

- strict cryptographic lineage;
- append-only idempotent writes;
- path/schema verification;
- public/private safety;
- no overwrite;
- no archive graph scanning;
- no progression interpretation;
- no Decision/Tape/Playbook integration;
- all existing tests green;
- changed-files Ruff green.


## 125. Dossier path identity includes lineage

ResearchDossier.dossier_hash identifies the Dossier snapshot itself.

ResearchDossierArchiveRecord.archive_record_hash identifies:

    Dossier snapshot
    + embedded WorkOrder archive
    + optional parent lineage

Therefore Dossier archive file identity uses archive_record_hash.

This preserves two distinct archive records when:

    dossier_hash is equal
    but prior_dossier_archive_record_hash differs

and prevents lineage from being silently collapsed by the filesystem path.


## 126. Dossier input-hash verification boundary

ResearchDossier.input_hash is a commitment created by Increment 8 from raw execution inputs that are not fully retained in the Dossier.

Increment 9 verifies:

    input_hash format
    + dossier_hash commitment to input_hash

but does not verify:

    raw execution inputs -> input_hash

A malicious actor who can replace both input_hash and recompute all enclosing semantic hashes could create a self-consistent but historically false record. Preventing that requires trusted archive provenance or retention of original inputs, which is outside Increment 9.


## 127. Replay-routing provenance acceptance

Start from one valid ReplayArchiveRecord and matching ResearchWorkOrderPolicy.

Construct a ResearchWorkOrder that:

- preserves source_archive_record_hash;
- preserves source_replay_result_hash;
- preserves source_cycle_as_of;
- remains internally semantically valid after rehashing;
- but changes source routing provenance to a different internally valid combination.

The WorkOrder archive builder must reject because the supplied replay's actual cohort transition does not match:

    ValueError("research work order replay lineage mismatch")

This test proves source hash equality is not treated as sufficient provenance.


## 128. Company-assessment semantic closure

For COMPANY_DEEP_DIVE Dossiers, archive validation must require:

- exactly one CompanyResearchAssessment per WorkOrder target;
- no assessment for a ticker outside WorkOrder targets;
- assessment.ticker is canonical uppercase target identity;
- assessment.evidence_source_hashes equals the sorted set of stored evidence-binding source_hash values whose target_ticker equals that ticker;
- assessment.independent_source_count equals the number of distinct independent source_ref values among those target bindings;
- assessment.covered_dimensions equals the normalized snapshot field names when normalized_evidence is present, otherwise ();
- normalized_evidence.ticker equals assessment.ticker;
- normalized_evidence.adapter_name equals WorkOrder.evidence_adapter;
- normalized_evidence field names are unique and lexical;
- normalized_evidence.normalized_payload_hash is a valid lowercase SHA-256 commitment;
- assessment.linkage_status is recomputed from the stored simple/hierarchical linkage objects;
- assessment.cautions is recomputed from linkage status and WorkOrder.minimum_independent_sources_per_company.

For THEME_REASSESSMENT:

    company_assessments == ()

Any mismatch raises:

    ValueError("inconsistent research company assessment")

## 129. Linkage snapshot semantic closure

Simple LinkageResult validation requires:

- ticker matches assessment ticker;
- all non-None numeric fields are finite.

HierarchicalLinkageSnapshot validation requires:

- target matches assessment ticker;
- all non-None numeric fields are finite;
- coefficients names are unique;
- coefficients are lexical by control name;
- coefficient values are finite;
- source_payload_hash is a lowercase SHA-256 string.

Because HierarchicalLinkageSnapshot retains every semantic field from HierarchicalLinkageResult except that coefficients are frozen as tuples, the validator should reconstruct the original semantic payload with:

    coefficients = {name: value for name, value in snapshot.coefficients}

and require:

    canonical_hash(reconstructed_payload)
      == snapshot.source_payload_hash

This hash is independently recoverable.

## 130. Evidence-binding semantic closure

For every ResearchEvidenceBinding stored in a Dossier:

- evidence.source_hash is lowercase 64-char SHA-256;
- evidence.payload_hash is lowercase 64-char SHA-256;
- evidence.source_ref is non-empty;
- evidence.source_type belongs to the supported evidence source registry;
- evidence.is_observed_fact is bool;
- independent is bool;
- direction is a valid ResearchEvidenceDirection;
- dimensions are non-empty, unique, stripped, and lexical;
- target_ticker obeys WorkOrder mode/target rules;
- model/inferred evidence cannot be marked independent;
- evidence observed_at, market_asof, and retrieved_at do not exceed Dossier.evidence_as_of.

The reader cannot recompute evidence.source_hash or payload_hash without the omitted EvidenceRecord payload. It validates their shape and all retained semantics only.

## 131. Finding semantic closure

For every stored ResearchFinding:

- finding_id is non-empty and unique;
- dimension and statement are non-empty;
- evidence_source_hashes are unique and lexical;
- every referenced hash exists among stored Dossier evidence bindings;
- target_ticker is within WorkOrder targets when present;
- a company finding cannot cite ticker-specific evidence from another target;
- OBSERVED_SYNTHESIS has non-None direction, at least one evidence reference, and all referenced evidence is observed fact;
- INFERENCE has non-None direction and at least one evidence reference;
- UNRESOLVED has direction None.

Recompute:

    unresolved_present
    contradictions_present

from stored findings + evidence bindings and require exact equality with Dossier fields.


## 132. WorkOrder policy archival invariant

ResearchWorkOrderArchiveRecord freezes the complete normalized ResearchWorkOrderPolicy.

This allows later readers to distinguish:

    same WorkOrder-like requirement shape
    under different policy regimes

and allows exact recomputation of:

    policy_hash
    requirement generation
    minimum-independent-source thresholds

The archive must not reduce policy history to a hash-only commitment.

## 133. WorkOrder policy mismatch acceptance

Start from a valid replay + WorkOrder + policy.

Supply a different normalized policy that changes any of:

- research dimensions;
- independent-source minima;
- linkage requirement flag;
- policy version.

Even if the WorkOrder itself is unchanged and internally valid, the archive builder rejects:

    ValueError("research work order policy mismatch")

## 134. WorkOrder policy round-trip acceptance

WorkOrder archive write/read preserves exact typed ResearchWorkOrderPolicy equality.

Reader independently recomputes:

    canonical_hash(asdict(work_order_policy))

and requires equality with:

    work_order.policy_hash

Then regenerate expected requirements and minima and require exact WorkOrder equality on those policy-derived fields.


## 135. Top-level and nested identity equality

ResearchWorkOrderArchiveRecord duplicates selected nested fields for navigation.

Require exact string/hash equality:

    record.source_cycle_as_of
      == record.work_order.source_cycle_as_of

    record.source_replay_archive_record_hash
      == record.work_order.source_archive_record_hash

    record.source_replay_result_hash
      == record.work_order.source_replay_result_hash

    record.work_order_hash
      == record.work_order.work_order_hash

ResearchDossierArchiveRecord requires:

    record.source_cycle_as_of
      == record.dossier.source_cycle_as_of

    record.evidence_as_of
      == record.dossier.evidence_as_of

    record.dossier_hash
      == record.dossier.dossier_hash

and the Dossier/embedded-WorkOrder lineage rules already defined.

These duplicated fields are not alternate spellings. They must be exact copies.

UTC normalization is used only for temporal ordering and path-date derivation.

Any mismatch raises the relevant archive lineage/value error.


## 136. Source replay cycle spelling is provenance

ResearchWorkOrder.source_cycle_as_of is copied directly from ReplayArchiveRecord.cycle_as_of by Increment 8.

Therefore WorkOrder archive construction requires exact string equality between those two fields.

Equivalent timestamps with different spellings are not accepted at this lineage boundary.

UTC normalization remains appropriate for:

- path-date derivation;
- Dossier parent temporal ordering;
- evidence/source-cycle temporal comparisons.
