# Increment 7 — Replay Cohort / Walk-forward Evaluation Design

Date: 2026-09-20
Status: approved in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: feature/replay-cohort-evaluation

## 1. Purpose

Evaluate historical replay archives as a cohort without pretending that research allocation is a directional price prediction.

Target question:

    When the system allocated more research attention to a theme,
    did later replay cycles contain more/new independent evidence change,
    and how did the system state subsequently evolve?

Increment 7 turns immutable replay archives into deterministic longitudinal transition records and descriptive cohort summaries.

It does not produce a single performance/accuracy score.

## 2. Scientific distinction

ResearchBudgetAllocator allocates research attention.

It does not predict:

- positive future return;
- negative future return;
- trade success;
- portfolio alpha.

Therefore this is invalid:

    FULL_DECISION_RESEARCH -> future price up -> success

and especially invalid for forced review, where FULL can mean:

    current independent evidence contradicts the theme strongly enough
    to warrant expensive reassessment

The primary walk-forward outcome in Increment 7 is future independent-evidence evolution.

Future scanner/lifecycle/tier values are retained as descriptive system transitions only.

## 3. Selected architecture

Add:

    src/decision_lab/replay_cohort.py

Primary public function:

    evaluate_replay_cohort(
        records: Sequence[ReplayArchiveRecord],
        horizons: Sequence[int] = (1, 3, 5),
    ) -> ReplayCohortResult

The evaluator is pure:

- no filesystem reads;
- no archive-directory scanning;
- no network;
- no clock;
- no random state;
- no price data.

Callers load and verify archive files separately with read_replay_archive.

## 4. Why records, not an archive root

Increment 7 does not accept:

    archive_root = ...

and scan the filesystem.

It accepts already-loaded ReplayArchiveRecord values.

Reasons:

- archive discovery/index policy remains separate;
- tests do not depend on directory enumeration;
- the evaluator has one clear responsibility;
- future database/object-store loaders can feed the same pure API.

## 5. Explicit non-goals

Increment 7 does not add:

- price returns;
- benchmark-relative returns;
- MAE/MFE;
- hit rate;
- alpha;
- Brier score;
- a unified success score;
- threshold calibration;
- automatic ResearchBudgetConfig attribution;
- automatic scanner/budget re-execution;
- archive directory scanning;
- manifests/indexes;
- persistent cohort files;
- charts/reports;
- company research;
- linkage;
- Tape;
- playbook routing;
- Decision Ledger;
- portfolio execution.

## 6. Relation to outcomes.py

Existing outcomes.py remains the trading-decision outcome layer.

Increment 7 must not import or call:

    evaluate_forward_outcomes
    missed_upside
    summarize_decisions

ResearchAllocation and Decision Object remain distinct evaluation units.

## 7. Archive-record validation

Although the public API accepts ReplayArchiveRecord objects, do not trust arbitrary manually-constructed records.

For each input record:

    rebuilt = build_replay_archive_record(record.replay_result)

Require:

    rebuilt == record

Otherwise raise:

    ValueError("invalid replay archive record")

This validates the archive record's semantic payload without depending on a filesystem path or private replay_archive helpers.

Canonical filename/cycle-directory verification remains the reader's responsibility.

## 8. Duplicate archive input

If the same archive_record_hash appears more than once:

    raise ValueError("duplicate replay archive record")

Do not silently deduplicate.

Duplicate input would otherwise distort cohort denominators.

## 9. Cycle normalization

Define one normalized replay-cycle instant in UTC.

Rules match replay/scanner time semantics:

### Date-only cycle_as_of

    YYYY-MM-DD

normalizes to:

    YYYY-MM-DD 23:59:59.999999 UTC

### Datetime cycle_as_of

- parse ISO datetime;
- naive datetime is interpreted as UTC;
- aware datetime is converted to UTC.

The original cycle_as_of string remains in outputs.

## 10. Cycle ordering

Sort input records by normalized cycle instant.

Input order must not affect any output or hash.

Distinct normalized instants on the same UTC calendar date are distinct replay cycles in v0.1.

## 11. Ambiguous cycle

If two distinct archive records normalize to the exact same cycle instant:

    raise ValueError("ambiguous cohort cycle")

Do not pick one by result hash, insertion order, or lexical ordering.

A later lineage/model-selection design can resolve parallel replays explicitly.

## 12. Horizon semantics

A horizon is measured in subsequent replay cycles, not calendar days.

For sorted cycles:

    C0, C1, C2, C3, ...

horizon 1 from C0 means C1.

horizon 3 from C0 means C3.

No assumption is made that archives are daily.

## 13. Horizon validation

Each horizon must be:

- an integer;
- not bool;
- > 0.

Duplicate horizons are rejected:

    ValueError("duplicate cohort horizon")

Invalid horizons raise:

    ValueError("cohort horizons must be positive integers")

Internally sort horizons ascending.

Horizon input order must not affect output.

## 14. Source population

For every source archive cycle and every source ReplayThemeRecord in that cycle, emit one ReplayCohortTransition per requested horizon.

Do not condition transition creation on future theme survival.

This is essential to avoid survivorship bias.

## 15. Right censoring

If source cycle index i has no cycle i+h:

    future_presence = RIGHT_CENSORED

Still emit the transition.

Fields requiring a future cycle are None.

Right-censored rows remain in source_n denominators and are counted explicitly.

Do not drop them.

## 16. Future theme absence

If the future replay cycle exists but theme_id is absent from future theme_records:

    future_presence = NOT_PRESENT

This does not mean:

- dormant;
- failed;
- SCAN_ONLY;
- priority = 0;
- evidence = neutral.

It only means the theme is not present in that replay's current theme-record universe.

## 17. Future theme presence

If the future replay cycle exists and contains the theme record:

    future_presence = PRESENT

A PRESENT future theme may still have:

    replay_status = NO_OBSERVATION

That remains distinct from NOT_PRESENT.

## 18. FuturePresence

Define:

    class FuturePresence(str, Enum):
        PRESENT = "PRESENT"
        NOT_PRESENT = "NOT_PRESENT"
        RIGHT_CENSORED = "RIGHT_CENSORED"

## 19. Current theme-record consistency

Before cohort evaluation, validate each ReplayCycleResult's duplicated current structures.

Within each cycle require:

- unique MarketObservationBatch.theme_id;
- unique ThemeScanResult.theme_id;
- unique ResearchAllocation.theme_id;
- unique ReplayThemeRecord.theme_id.

Also require exact top-level coverage:

    set(scan_result.theme_id)
      == set(routed theme_record.theme_id)

    set(allocation.theme_id)
      == set(routed theme_record.theme_id)

    set(market_batch.theme_id)
      == set(registered theme_record.theme_id)

Every top-level market batch, scan result, and allocation must therefore belong to exactly one current ReplayThemeRecord.

All top-level MarketObservationBatch.cycle_as_of values must equal ReplayCycleResult.cycle_as_of.

All top-level ThemeScanResult.as_of values and ResearchAllocation.as_of values must equal ReplayCycleResult.cycle_as_of.

All ThemeScanResult.config_hash values within one replay cycle must be identical. Multiple scanner config hashes in one cycle raise:

    ValueError("multiple scanner config hashes in replay cycle")

For every ReplayThemeRecord:

### NO_OBSERVATION

Require:

    registered is True
    scan_result is None
    allocation is None

and no top-level scan/allocation exists for that theme.

### ROUTED

Require:

    scan_result is not None
    allocation is not None

and both exactly equal the top-level objects for that theme.

If registered is True:

    market_batch is not None

and it must exactly equal the top-level market batch for that theme.

If registered is False:

    market_batch is None

If any consistency rule fails:

    raise ValueError("inconsistent replay theme record")

## 20. Allocation-to-scan consistency

For every routed record require:

    allocation.theme_id == scan_result.theme_id == theme_record.theme_id

and:

    allocation.source_scan_result_hash
      == canonical_hash(asdict(scan_result))

Otherwise:

    raise ValueError("allocation scan-result hash mismatch")

This prevents cohort logic from analyzing an allocation bound to a different scan state.

## 21. Observation/theme consistency

For every combined_observation:

- theme_id must correspond to a ReplayThemeRecord in that cycle.

If not:

    raise ValueError("observation theme missing from replay records")

This ensures NOT_PRESENT really means there was no current observation for the theme.

## 22. Independent evidence source collapse

Evidence evolution is derived from:

    replay_result.combined_observations

not from future lifecycle/tier.

Group observations by:

    (theme_id, source_ref)

Within one theme/source require consistent:

- source_type;
- is_independent.

Conflicting metadata raises:

    ValueError("conflicting cohort source metadata")

Non-independent sources do not enter IndependentEvidenceState counts.

## 23. Per-source direction

For one independent source_ref, aggregate direction exactly with contradiction precedence:

1. if any row is CONTRADICTING -> CONTRADICTING;
2. else if any row is SUPPORTING -> SUPPORTING;
3. else -> NEUTRAL.

Multiple rows from one source_ref count as one independent source.

## 24. EvidenceClass

Define:

    class EvidenceClass(str, Enum):
        NO_INDEPENDENT = "NO_INDEPENDENT"
        SUPPORT_ONLY = "SUPPORT_ONLY"
        CONTRADICTION_PRESENT = "CONTRADICTION_PRESENT"
        NEUTRAL_ONLY = "NEUTRAL_ONLY"
        MIXED = "MIXED"

Classification:

### NO_INDEPENDENT

    independent_source_count == 0

### MIXED

    supporting_source_count > 0
    and contradicting_source_count > 0

### CONTRADICTION_PRESENT

    contradicting_source_count > 0
    and supporting_source_count == 0

Neutral sources may coexist.

### SUPPORT_ONLY

    supporting_source_count > 0
    and contradicting_source_count == 0

Neutral sources may coexist.

### NEUTRAL_ONLY

At least one independent source, with zero supporting and zero contradicting sources.

## 25. IndependentEvidenceState

Define frozen dataclass:

    IndependentEvidenceState
      evidence_class: EvidenceClass
      independent_source_count: int
      supporting_source_count: int
      contradicting_source_count: int
      neutral_source_count: int
      supporting_source_refs: tuple[str, ...]
      contradicting_source_refs: tuple[str, ...]
      neutral_source_refs: tuple[str, ...]

Source-ref tuples are sorted.

This makes evidence transitions auditable without re-reading every observation.

## 26. Source evidence state

For every source theme transition, derive source_evidence_state from source combined_observations.

A model-only theme such as Rates can therefore have:

    EvidenceClass.NO_INDEPENDENT

even though a valid ThemeScanResult exists.

## 27. Future evidence state

If future_presence is PRESENT:

    derive IndependentEvidenceState from future combined_observations

If future theme is PRESENT but NO_OBSERVATION, the state is normally:

    NO_INDEPENDENT

If future_presence is NOT_PRESENT or RIGHT_CENSORED:

    future_evidence_state = None

## 28. ContradictionTransition

Absence of future independent evidence must not be called contradiction resolution.

Define:

    class ContradictionTransition(str, Enum):
        ABSENT = "ABSENT"
        EMERGED = "EMERGED"
        PERSISTED = "PERSISTED"
        RESOLVED = "RESOLVED"
        UNASSESSED = "UNASSESSED"

## 29. Contradiction transition rules

Let:

    S = source_evidence_state
    F = future_evidence_state

### UNASSESSED

If any is true:

- future_presence is not PRESENT;
- S.independent_source_count == 0;
- F.independent_source_count == 0.

### EMERGED

If:

    S.contradicting_source_count == 0
    F.contradicting_source_count > 0

with both source and future independently observed.

### PERSISTED

If:

    S.contradicting_source_count > 0
    F.contradicting_source_count > 0

### RESOLVED

If:

    S.contradicting_source_count > 0
    F.contradicting_source_count == 0

with future independent evidence present.

### ABSENT

Both source and future have independent evidence and neither contains contradiction.

## 30. Evidence class change

Define:

    evidence_class_changed: bool | None

If both source and future have at least one independent source:

    source.evidence_class != future.evidence_class

Otherwise:

    None

This avoids treating loss of evidence coverage as a directional evidence-class change.

## 31. Raw evidence-count deltas

If future_presence is PRESENT:

    support_delta =
        future.supporting_source_count
        - source.supporting_source_count

    contradiction_delta =
        future.contradicting_source_count
        - source.contradicting_source_count

These are descriptive count deltas.

They are not interpreted as success/failure.

For NOT_PRESENT or RIGHT_CENSORED:

    deltas = None

## 32. RoutingIntent

ResearchTier alone is insufficient.

Define:

    class RoutingIntent(str, Enum):
        NO_OBSERVATION = "NO_OBSERVATION"
        SCAN_ONLY = "SCAN_ONLY"
        ORDINARY_THEME_RESEARCH = "ORDINARY_THEME_RESEARCH"
        ORDINARY_FULL_RESEARCH = "ORDINARY_FULL_RESEARCH"
        FORCED_FULL_REVIEW = "FORCED_FULL_REVIEW"
        FORCED_REVIEW_CAPACITY_MISSED = "FORCED_REVIEW_CAPACITY_MISSED"

## 33. Routing intent derivation

For source ReplayThemeRecord:

### NO_OBSERVATION

If:

    replay_status == NO_OBSERVATION

### FORCED_FULL_REVIEW

If:

    replay_status == ROUTED
    scan_result.forced_review is True
    allocation.forced_review is True
    allocation.tier == FULL_DECISION_RESEARCH

### FORCED_REVIEW_CAPACITY_MISSED

If:

    scan_result.forced_review is True
    allocation.forced_review is True
    allocation.tier == SCAN_ONLY
    "forced review capacity exhausted"
        in allocation.allocation_reasons

### ORDINARY_FULL_RESEARCH

If:

    forced_review is False
    tier == FULL_DECISION_RESEARCH

### ORDINARY_THEME_RESEARCH

If:

    forced_review is False
    tier == THEME_RESEARCH

### SCAN_ONLY

If:

    forced_review is False
    tier == SCAN_ONLY

Any other forced-review/tier combination is invalid:

    ValueError("unsupported forced-review allocation state")

## 34. Forced-review flag consistency

For routed records require:

    scan_result.forced_review == allocation.forced_review

Otherwise:

    ValueError("forced-review flag mismatch")

A non-forced allocation must not carry:

    "forced review capacity exhausted"

in allocation_reasons.

A forced FULL allocation must not carry that capacity-exhausted reason.

## 35. TierTransition

Define:

    class TierTransition(str, Enum):
        SAME = "SAME"
        ESCALATED = "ESCALATED"
        DEESCALATED = "DEESCALATED"
        UNASSESSED = "UNASSESSED"

Tier ordering:

    SCAN_ONLY < THEME_RESEARCH < FULL_DECISION_RESEARCH

If either source or future tier is None:

    UNASSESSED

Otherwise compare ranks.

RoutingIntent is not ranked.

## 36. Future system state is descriptive

For future_presence PRESENT capture:

- future_registered;
- future_replay_status;
- future lifecycle recommendation;
- future forced_review;
- future research_priority;
- future evidence_confidence;
- future novelty_score;
- future allocation tier;
- future scanner config hash.

These are not independent ground truth.

They can depend on:

- prior scan history;
- prior allocation history;
- scanner config;
- budget config;
- current registry state.

## 37. Scanner config lineage

ThemeScanResult includes:

    config_hash

Therefore transitions expose:

    source_scanner_config_hash
    future_scanner_config_hash
    scanner_config_changed

If either scan result is absent:

    scanner_config_changed = None

## 38. Budget config attribution limitation

ResearchAllocation does not contain a budget_config_hash.

ReplayCycleResult.input_hash commits to budget config indirectly, but the archive does not contain the semantic ReplayCycleInput needed to identify or independently reconstruct that config.

Therefore Increment 7 must not claim:

    "ResearchBudgetConfig vX had Y% accuracy"

or attribute tier transitions to one budget config version.

## 39. ReplayCohortTransition

Define frozen dataclass:

    ReplayCohortTransition
      source_cycle_index: int
      future_cycle_index: int | None
      source_cycle_as_of: str
      future_cycle_as_of: str | None
      horizon_cycles: int

      source_archive_record_hash: str
      future_archive_record_hash: str | None

      theme_id: str
      routing_intent: RoutingIntent

      source_registered: bool
      future_presence: FuturePresence
      future_registered: bool | None

      source_evidence_state: IndependentEvidenceState
      future_evidence_state: IndependentEvidenceState | None
      support_delta: int | None
      contradiction_delta: int | None
      contradiction_transition: ContradictionTransition
      evidence_class_changed: bool | None

      source_replay_status: ReplayStatus
      future_replay_status: ReplayStatus | None

      source_scanner_config_hash: str | None
      future_scanner_config_hash: str | None
      scanner_config_changed: bool | None

      source_priority: float | None
      future_priority: float | None
      priority_delta: float | None

      source_confidence: float | None
      future_confidence: float | None
      confidence_delta: float | None

      source_novelty: float | None
      future_novelty: float | None
      novelty_delta: float | None

      source_lifecycle: str | None
      future_lifecycle: str | None

      source_forced_review: bool | None
      future_forced_review: bool | None

      source_tier: ResearchTier | None
      future_tier: ResearchTier | None
      tier_transition: TierTransition

## 40. Source system fields

For source NO_OBSERVATION:

    source_priority = None
    source_confidence = None
    source_novelty = None
    source_lifecycle = None
    source_forced_review = None
    source_tier = None
    source_scanner_config_hash = None

Do not synthesize zeros.

## 41. Future PRESENT + NO_OBSERVATION

For a future theme that is PRESENT but NO_OBSERVATION:

    future_registered = True
    future_replay_status = NO_OBSERVATION

and scanner/allocation fields are None.

Do not convert this into SCAN_ONLY.

## 42. Future NOT_PRESENT

For NOT_PRESENT:

    future_registered = None
    future_replay_status = None
    future_evidence_state = None
    all future scanner/allocation fields = None
    all numeric deltas = None
    tier_transition = UNASSESSED
    contradiction_transition = UNASSESSED

## 43. RIGHT_CENSORED

For RIGHT_CENSORED:

- future cycle index/hash/as_of are None;
- future presence is RIGHT_CENSORED;
- all future theme/evidence/system fields are None;
- deltas are None;
- transitions are UNASSESSED.

RIGHT_CENSORED is distinct from NOT_PRESENT.

## 44. Priority/confidence/novelty deltas

If both source and future numeric values exist:

    delta = future - source

Otherwise:

    None

No imputation.

## 45. Forced-review descriptive transitions

For rows where source/future forced_review are both known, summary may count:

- emerged: False -> True;
- persisted: True -> True;
- resolved: True -> False.

False -> False is not a special event.

If either side is None, do not count a forced-review transition.

## 46. ReplayCohortSummary

Group summaries by:

    (routing_intent, horizon_cycles)

Define frozen dataclass:

    ReplayCohortSummary
      routing_intent: RoutingIntent
      horizon_cycles: int

      source_n: int
      future_cycle_available_n: int
      right_censored_n: int
      future_present_n: int
      future_not_present_n: int
      future_independent_evidence_n: int

      contradiction_unassessed_n: int
      contradiction_absent_n: int
      contradiction_emerged_n: int
      contradiction_persisted_n: int
      contradiction_resolved_n: int

      source_independent_evidence_n: int
      evidence_class_comparable_n: int
      evidence_class_changed_n: int

      tier_unassessed_n: int
      tier_same_n: int
      tier_escalated_n: int
      tier_deescalated_n: int

      forced_review_unassessed_n: int
      forced_review_inactive_n: int
      forced_review_emerged_n: int
      forced_review_persisted_n: int
      forced_review_resolved_n: int

      scanner_config_unassessed_n: int
      scanner_config_same_n: int
      scanner_config_changed_n: int

      priority_delta_n: int
      mean_priority_delta: float | None

      confidence_delta_n: int
      mean_confidence_delta: float | None

      novelty_delta_n: int
      mean_novelty_delta: float | None

## 47. Summary denominator identities

For every summary require:

    source_n
      == future_cycle_available_n + right_censored_n

and:

    future_cycle_available_n
      == future_present_n + future_not_present_n

No hidden dropping.

## 48. Mean delta denominators

For priority/confidence/novelty:

- only non-None deltas enter the mean;
- expose the count used in the mean;
- if count == 0, mean = None.

Never silently treat missing as zero.

## 49. Evidence-class-change summary

Increment:

    source_independent_evidence_n

when source_evidence_state.independent_source_count > 0.

Increment:

    evidence_class_comparable_n

only when evidence_class_changed is not None.

Increment:

    evidence_class_changed_n

only when evidence_class_changed is True.

Therefore:

    evidence_class_changed_n
      <= evidence_class_comparable_n

Rows with None are never treated as unchanged.

## 50. Contradiction summary

Count each transition into exactly one ContradictionTransition bucket.

Therefore:

    source_n
      == contradiction_unassessed_n
       + contradiction_absent_n
       + contradiction_emerged_n
       + contradiction_persisted_n
       + contradiction_resolved_n

This makes evidence coverage gaps visible.

## 51. Tier summary

Count each transition into exactly one TierTransition bucket.

Therefore:

    source_n
      == tier_unassessed_n
       + tier_same_n
       + tier_escalated_n
       + tier_deescalated_n

## 52. Forced-review and scanner-config denominator identities

Forced-review state forms a complete partition:

    source_n
      == forced_review_unassessed_n
       + forced_review_inactive_n
       + forced_review_emerged_n
       + forced_review_persisted_n
       + forced_review_resolved_n

where inactive means:

    False -> False

and unassessed means either side is None.

Scanner-config comparison also forms a complete partition:

    source_n
      == scanner_config_unassessed_n
       + scanner_config_same_n
       + scanner_config_changed_n

where unassessed means either source/future scanner config hash is None.

## 53. Cohort metadata and limitations

ReplayCohortResult includes a fixed limitations tuple:

    (
      "future system state is descriptive, not independent ground truth",
      "budget config identity is not recoverable from ReplayCycleResult alone",
      "allocation tier records routing intent, not proof downstream research executed",
      "research allocation is not evaluated as a directional price prediction",
    )

These strings are part of v0.1 result semantics and result_hash.

## 54. ReplayCohortResult

Define frozen dataclass:

    ReplayCohortResult
      schema_version: str
      evaluation_scope: str
      horizons: tuple[int, ...]
      cycles: tuple[str, ...]
      archive_record_hashes: tuple[str, ...]
      transitions: tuple[ReplayCohortTransition, ...]
      summaries: tuple[ReplayCohortSummary, ...]
      limitations: tuple[str, ...]
      input_hash: str
      result_hash: str

Constants:

    schema_version = "0.1"

    evaluation_scope =
      "evidence_evolution_and_descriptive_system_transition"

## 55. Cohort input hash

After archive validation and cycle sorting:

    input_payload = {
      "schema_version": "0.1",
      "evaluation_scope": ...,
      "horizons": [...sorted horizons...],
      "archive_record_hashes": [
        record.archive_record_hash
        in normalized cycle order
      ],
    }

Then:

    input_hash = canonical_hash(input_payload)

Input record ordering and horizon ordering do not affect input_hash.

## 56. Cohort result hash

Build result payload with result_hash omitted:

    result_payload = {
      "schema_version": ...,
      "evaluation_scope": ...,
      "horizons": ...,
      "cycles": ...,
      "archive_record_hashes": ...,
      "transitions": [asdict(...) ...],
      "summaries": [asdict(...) ...],
      "limitations": ...,
      "input_hash": ...,
    }

Then:

    result_hash = canonical_hash(result_payload)

No self-reference.

## 57. Deterministic ordering

cycles and archive_record_hashes:

    normalized cycle order

transitions:

    (
      source_cycle_index,
      horizon_cycles,
      theme_id
    )

summaries:

    (
      horizon_cycles,
      routing_intent.value
    )

All source-ref tuples:

    lexical order

## 58. Empty cohort

Empty records are valid.

Result:

    cycles = ()
    archive_record_hashes = ()
    transitions = ()
    summaries = ()

with deterministic input_hash/result_hash.

Requested horizons remain in the result.

## 59. One-cycle cohort

A one-cycle cohort produces source theme transitions for every requested horizon, all RIGHT_CENSORED.

This preserves source denominators.

## 60. New future themes

A theme that appears only in a future cycle and was absent from the source cycle does not create a backward transition.

Increment 7 evaluates outcomes of source routing decisions.

Theme-emergence cohort analysis is deferred.

## 61. Evidence evolution versus system evolution

Primary evidence fields:

- IndependentEvidenceState;
- support_delta;
- contradiction_delta;
- ContradictionTransition;
- evidence_class_changed.

Descriptive system fields:

- lifecycle;
- priority;
- confidence;
- novelty;
- forced review;
- allocation tier;
- scanner config hash.

Do not combine them into one score.

## 62. No directional labels

Do not add fields named:

    success
    failure
    correct
    incorrect
    accuracy
    performance_score
    reward

Version 0.1 remains descriptive.

## 63. No price or ticker-return fields

ReplayCohortTransition and ReplayCohortSummary contain no:

- return;
- alpha;
- benchmark return;
- MAE;
- MFE.

A future price-outcome design must state a direction-specific hypothesis first.

## 64. Forced review interpretation

FORCED_FULL_REVIEW means:

    the system spent a FULL slot because current evidence demanded reassessment

It does not mean:

    the theme should rise
    or
    the theme should fall

Useful cohort questions include:

- did contradiction persist?
- did contradiction resolve under later independent evidence?
- did the theme remain present?
- did future forced review persist?
- was a capacity-missed forced review followed by material evidence change?

## 65. Capacity-missed cohort

FORCED_REVIEW_CAPACITY_MISSED is a first-class routing intent.

This creates a future calibration comparison between:

    forced review that received FULL capacity

and:

    forced review that was blocked by capacity

Increment 7 reports their later evidence transitions descriptively.

It does not claim causal effects of receiving research capacity.

## 66. Allocation is not execution

Increment 7 observes:

    what research tier was allocated

It does not observe:

    whether the downstream research was actually performed
    how many analyst/compute hours were spent
    what the downstream research discovered
    whether that research changed a later decision

Therefore cohort results measure where the allocator routed attention relative to later evidence evolution.

They do not estimate return on research effort.

A later FULL_DECISION_RESEARCH executor must create its own immutable execution/completion artifacts before value-of-research can be evaluated.

## 67. Scanner config changes

Evidence evolution remains interpretable across scanner-config changes because it is re-derived from archived current observations.

System transition comparisons across changed scanner configs remain descriptive and expose scanner_config_changed.

## 68. Budget config changes

Because budget config identity is unavailable, tier-transition summaries may mix allocations generated under different unknown budget configurations.

The limitation is explicit.

Do not infer budget-threshold calibration from tier-transition counts alone.

## 69. First acceptance cohort

Create at least three valid replay archive records using run_replay_cycle.

### Cycle C0

Include:

- DataCenter-like registered forced contradiction -> FORCED_FULL_REVIEW;
- Genomics-like registered strong independent support -> ORDINARY_FULL_RESEARCH;
- Rates model-only unknown -> SCAN_ONLY;
- Quiet registered no evidence -> NO_OBSERVATION.

### Cycle C1

Construct later evidence such that:

- DataCenter contradiction persists;
- Genomics remains independently observed without contradiction;
- Rates is absent from the replay;
- Quiet remains PRESENT but NO_OBSERVATION.

Expected horizon-1 outcomes include:

- DataCenter contradiction PERSISTED;
- Rates future_presence NOT_PRESENT;
- Quiet future_presence PRESENT and future_replay_status NO_OBSERVATION.

### Cycle C2

Construct later evidence such that:

- DataCenter has independent evidence with contradiction gone -> RESOLVED;
- Genomics gains independent contradiction -> EMERGED;
- Rates reappears model-only.

Expected horizon-2 outcomes from C0 include:

- DataCenter contradiction RESOLVED;
- Genomics contradiction EMERGED;
- Rates PRESENT but future evidence class NO_INDEPENDENT.

## 70. Right-censor acceptance

For C1 and C2 source rows at horizons with no sufficiently later archive:

    RIGHT_CENSORED

must be emitted, not dropped.

Summary denominators must include them.

## 71. NOT_PRESENT acceptance

If Rates is absent in C1:

- no future theme record is synthesized;
- future tier/lifecycle/priority remain None;
- future_presence is NOT_PRESENT;
- contradiction transition is UNASSESSED;
- tier transition is UNASSESSED.

## 72. NO_OBSERVATION acceptance

If Quiet is still registered in C1 but produces no current observation:

- future_presence is PRESENT;
- future_replay_status is NO_OBSERVATION;
- future_tier is None;
- future evidence state is NO_INDEPENDENT.

This proves NOT_PRESENT != NO_OBSERVATION != SCAN_ONLY.

## 73. Capacity-missed acceptance

Construct one valid replay with:

    forced review = True
    full_decision_slots = 0

so allocator emits:

    SCAN_ONLY
    "forced review capacity exhausted"

Cohort routing_intent must be:

    FORCED_REVIEW_CAPACITY_MISSED

No budget-config identity is inferred from the archive.

## 74. Source-metadata conflict acceptance

Construct or tamper an in-memory validly-hashed replay result so the same:

    (theme_id, source_ref)

has conflicting:

    is_independent
    or source_type

Cohort evaluation must reject:

    ValueError("conflicting cohort source metadata")

Do not collapse conflicting sources.

## 75. Internal replay-consistency acceptance

Evaluation rejects archive records whose replay result is hash-valid but semantically inconsistent, including:

- duplicate theme records;
- routed theme record not matching top-level scan;
- routed allocation not matching top-level allocation;
- allocation source_scan_result_hash mismatch;
- NO_OBSERVATION with top-level allocation;
- combined observation for a theme absent from theme_records.

Archive integrity alone does not make these longitudinal semantics valid.

## 76. Input-order determinism acceptance

Reverse:

- archive-record input order;
- horizon input order.

Result must be exactly equal.

## 77. Duplicate-cycle acceptance

Two distinct archive records with the same normalized cycle instant:

    ValueError("ambiguous cohort cycle")

Two copies of the same archive record:

    ValueError("duplicate replay archive record")

## 78. Horizon acceptance

Reject:

- 0;
- negative values;
- True/False;
- duplicate horizon values;
- floats;
- strings.

## 79. Summary acceptance

For every (routing_intent, horizon) group test:

    source_n
      == available + censored

    available
      == present + not_present

    source_n
      == all contradiction buckets

    source_n
      == all tier-transition buckets

and mean-delta counts exactly match non-None transition deltas.

Also require:

    source_n
      == forced_review_unassessed_n
       + forced_review_inactive_n
       + forced_review_emerged_n
       + forced_review_persisted_n
       + forced_review_resolved_n

    source_n
      == scanner_config_unassessed_n
       + scanner_config_same_n
       + scanner_config_changed_n

and:

    evidence_class_changed_n
      <= evidence_class_comparable_n.

## 80. Hash determinism acceptance

Same validated archive set + same horizon set:

    same input_hash
    same result_hash

regardless of input ordering.

Changing:

- one archive record;
- one horizon;

must change input_hash.

## 81. Purity

evaluate_replay_cohort must not:

- read files;
- write files;
- inspect directories;
- call read_replay_archive;
- call time.now;
- inspect environment;
- call network;
- mutate input records.

## 82. Proposed public types

Export:

    EvidenceClass
    FuturePresence
    RoutingIntent
    ContradictionTransition
    TierTransition
    IndependentEvidenceState
    ReplayCohortTransition
    ReplayCohortSummary
    ReplayCohortResult
    evaluate_replay_cohort

Keep helper functions private.

## 83. Proposed files

Create:

    src/decision_lab/replay_cohort.py

Create:

    tests/test_replay_cohort.py

Modify for exports only:

    src/decision_lab/__init__.py

Do not modify behavior in:

    src/decision_lab/replay.py
    src/decision_lab/replay_archive.py
    src/decision_lab/scanner.py
    src/decision_lab/research_budget.py
    src/decision_lab/market_observation.py
    src/decision_lab/outcomes.py
    src/decision_lab/themes.py
    src/decision_lab/universe.py
    src/decision_lab/ledger.py
    src/decision_lab/tape.py
    src/decision_lab/playbooks.py

If cohort implementation appears to require changing those semantics, stop and upgrade scope.

## 84. Public-repository safety

Increment 7 operates on replay archives already affirmed safe for their storage destination.

It does not broaden data retention.

Tests use public-safe synthetic observations/configs.

Do not add holdings, sizing, account data, confidential employer data, or licensed raw market payloads.

## 85. Deferred work

Deliberately deferred:

- price outcome evaluation;
- directional hypothesis evaluation;
- budget-config lineage schema;
- scanner/budget calibration;
- causal value-of-research estimation;
- archive discovery/indexing;
- persistent cohort artifacts;
- dashboards;
- report generation;
- automated scheduling;
- FULL_DECISION_RESEARCH executor.

## 86. Completion criterion

Increment 7 is complete when an ordered or unordered set of immutable replay archive records can be transformed deterministically into:

    source routing intent
      x future replay-cycle horizon
      -> evidence evolution
      + descriptive system transition
      + explicit missingness/right-censoring

with:

- no survivorship filtering;
- no price interpretation;
- no single performance score;
- no false budget-config attribution;
- no claim that an allocated research tier proves downstream research execution;
- NO_OBSERVATION, NOT_PRESENT, and RIGHT_CENSORED kept distinct;
- independent contradiction emergence/persistence/resolution requiring actual independent evidence;
- deterministic cohort hashes and summaries;
- no filesystem/network side effects;
- all existing tests green;
- changed-files Ruff green.
