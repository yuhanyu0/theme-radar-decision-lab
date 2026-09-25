# Increment 11 — Research Decision Readiness Design

Date: 2026-09-24
Status: approved in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: feature/research-decision-readiness

## 1. Purpose

Add an explicit epistemic gate between Research Progression and downstream decision machinery.

Target chain:

    Sequence[ResearchDossierArchiveRecord]
        -> evaluate_research_progression(...)
        -> explicit candidate leaf
        -> ResearchDecisionReadinessAssessment
        -> later Tape / Playbook / Decision integration

Increment 11 answers:

    is the selected research state sufficiently closed and complete
    to enter downstream decision analysis?

It does not answer:

    should we trade?
    which fork is canonical?
    is the thesis true?
    is Tape valid?
    which playbook should fire?

## 2. Core invariant

Decision readiness is not trading permission.

Therefore:

    READY
      != BUY
      != trade permission
      != thesis correctness
      != Tape confirmation
      != playbook selection
      != calibrated probability

The only meaning of READY in Increment 11 is:

    research-ready for downstream decision analysis

## 3. Selected architecture

Add one module:

    src/decision_lab/research_decision_readiness.py

Primary API:

    assess_research_decision_readiness(
        records: Sequence[ResearchDossierArchiveRecord],
        candidate_archive_record_hash: str,
    ) -> ResearchDecisionReadinessAssessment

The function is pure and deterministic.

It internally calls:

    evaluate_research_progression(records)

so Increment 11 inherits Increment 9 archive validation and Increment 10 progression semantics rather than trusting a caller-constructed progression report.

## 4. Explicit candidate selection

The caller must provide:

    candidate_archive_record_hash

Increment 11 never selects a candidate by:

- latest evidence_as_of;
- lexicographic hash;
- highest completion;
- lowest burden;
- shortest closure time;
- first/last input order;
- any score.

This prevents implicit canonical-branch selection.

## 5. Candidate existence

The candidate hash must identify exactly one supplied archive record.

If the candidate is absent from the evaluated record set:

    raise ValueError

Duplicate archive identities are already rejected by Increment 10.

## 6. Status enum

Define:

    class ResearchDecisionReadinessStatus(str, Enum):
        READY = "READY"
        NOT_READY = "NOT_READY"
        INDETERMINATE = "INDETERMINATE"

Interpretation:

READY:
- all local sufficiency gates pass;
- lineage is complete;
- the selected candidate is the unique observed leaf.

NOT_READY:
- at least one known local sufficiency gate fails.

INDETERMINATE:
- all local sufficiency gates pass;
- but the supplied progression surface cannot establish one determinate current lineage.

Known insufficiency takes precedence over indeterminacy.

## 7. Why three states

A binary ready/not-ready flag would conflate:

- known research insufficiency;
- missing lineage;
- unresolved branch selection.

Those are different epistemic failures.

Therefore:

    NOT_READY != INDETERMINATE

## 8. Fixed v0.1 readiness law

Increment 11 uses one frozen v0.1 readiness law.

Define:

    READINESS_POLICY_VERSION = "0.1"

and a canonical policy hash over the fixed gate configuration.

The caller cannot weaken gates through runtime flags in this increment.

This avoids turning readiness into a caller-selected threshold.

## 9. Gate representation

Define:

    ResearchDecisionReadinessGate

with:

    CANDIDATE_IS_LEAF
    DOSSIER_COMPLETE
    EXECUTION_CLOSED
    NO_UNSATISFIED_REQUIREMENTS
    NO_UNRESOLVED_FINDINGS
    GLOBAL_SOURCE_MINIMUM_MET
    COMPANY_SOURCE_MINIMUMS_MET
    LINEAGE_COMPLETE
    UNIQUE_OBSERVED_LEAF

Define:

    ResearchDecisionReadinessGateResult(
        gate,
        passed,
    )

Gate order is fixed exactly as listed above.

No weighted score is calculated.

## 10. Local sufficiency gates

The first seven gates are local sufficiency gates:

    CANDIDATE_IS_LEAF
    DOSSIER_COMPLETE
    EXECUTION_CLOSED
    NO_UNSATISFIED_REQUIREMENTS
    NO_UNRESOLVED_FINDINGS
    GLOBAL_SOURCE_MINIMUM_MET
    COMPANY_SOURCE_MINIMUMS_MET

If any local sufficiency gate fails:

    status = NOT_READY

regardless of lineage or branch ambiguity.

## 11. Candidate must be a leaf

A historical intermediate snapshot is not treated as the current research state.

Therefore:

    candidate_archive_record_hash in report.leaves

is required for local sufficiency.

A valid non-leaf candidate is assessed as NOT_READY rather than rejected.

## 12. COMPLETE is required

Require:

    candidate snapshot.status == ResearchDossierStatus.COMPLETE

This respects the frozen WorkOrder requirement universe.

Increment 11 does not add new evidence requirements.

## 13. CLOSED is independently required

Require:

    candidate snapshot.closure == ResearchExecutionClosure.CLOSED

This is intentionally separate from COMPLETE.

A dossier may be:

    COMPLETE + OPEN

but Decision Readiness remains NOT_READY until research execution is explicitly closed.

This prevents automatic promotion the instant coverage flips COMPLETE.

Likewise:

    BLOCKED_INSUFFICIENT_EVIDENCE + CLOSED

remains NOT_READY.

## 14. No unsatisfied requirements

Require:

    candidate burden.unsatisfied_requirements == ()

This is deliberately redundant with valid COMPLETE semantics.

The redundancy makes the readiness gate auditable and protects against later semantic drift.

## 15. No unresolved findings

Require:

    candidate burden.unresolved_finding_ids == ()

ResearchDossierStatus.COMPLETE does not by itself mean there are no unresolved findings.

Therefore this is an additional readiness gate.

## 16. Independent-source minimum

Require:

    candidate burden.independent_source_deficit == 0

This uses the frozen WorkOrder source minimum already encoded by Increment 10 burden semantics.

## 17. Company source minimums

Require every company burden:

    independent_source_deficit == 0

Increment 11 must not create new company evidence thresholds.

## 18. Linkage policy is not rewritten

Increment 11 does not independently require:

    CompanyLinkageStatus.USABLE

unless the frozen WorkOrder already required usable linkage and therefore encoded it in COMPLETE/unsatisfied requirements.

This preserves Increment 8/9 WorkOrder policy authority.

Optional linkage is not silently promoted into a new hard gate.

## 19. Contradictions do not automatically block readiness

A valid completed research package may contain contradicting evidence.

Therefore:

    contradictions_present

is surfaced as a caution but is not a blocking gate.

An unresolved contradiction can still block through:

    NO_UNRESOLVED_FINDINGS

if represented as an unresolved finding.

This preserves:

    contradiction != ignorance

## 20. Determinacy gates

The final two gates are determinacy gates:

    LINEAGE_COMPLETE
    UNIQUE_OBSERVED_LEAF

They are evaluated only after local sufficiency is known.

If all local sufficiency gates pass but either determinacy gate fails:

    status = INDETERMINATE

## 21. Lineage completeness

The selected candidate must belong to exactly one maximal trajectory ending at that candidate.

That trajectory must have:

    lineage_complete is True

An orphan-start trajectory therefore cannot produce READY.

If locally sufficient:

    orphan-start -> INDETERMINATE

because the missing prefix prevents a full historical readiness claim.

## 22. Unique observed leaf

Require:

    report.leaves == (candidate_archive_record_hash,)

after deterministic ordering.

If other leaves exist under the same WorkOrder:

    status = INDETERMINATE

provided local sufficiency passes.

This includes:

- forks;
- multiple explicit roots;
- additional orphan suffixes.

Increment 11 does not choose among them.

## 23. Competing leaves

Assessment records:

    competing_leaf_archive_record_hashes

defined as every report leaf except the selected candidate, sorted lexicographically.

This is descriptive evidence for branch ambiguity.

## 24. Candidate-local sufficiency

Assessment includes:

    candidate_sufficient: bool

defined as:

    all(local sufficiency gates pass)

This does not by itself imply READY.

Example:

    candidate_sufficient == True
    competing leaves exist
    status == INDETERMINATE

## 25. Selection determinacy

Assessment includes:

    selection_determinate: bool

defined as:

    LINEAGE_COMPLETE
    and UNIQUE_OBSERVED_LEAF

Again, this is not a score.

## 26. Historical reopening

For the selected candidate trajectory, surface:

    execution_reopen_count

A prior CLOSED -> OPEN event does not automatically block current readiness.

It is historical context.

## 27. Historical completion loss

For the selected candidate trajectory, surface:

    completion_loss_count

A prior COMPLETE -> non-COMPLETE event does not automatically block current readiness if the current selected leaf again satisfies all gates.

It remains visible as cautionary history.

## 28. Company cautions

Preserve current company cautions from the selected snapshot as:

    ResearchDecisionReadinessCompanyCaution(
        ticker,
        caution,
    )

sorted by:

    (ticker, caution)

Company cautions are descriptive.

They do not override the frozen WorkOrder unless another explicit readiness gate already fails.

## 29. Assessment record

Define:

    ResearchDecisionReadinessAssessment

Required fields:

    policy_version
    policy_hash
    progression_report_hash
    work_order_archive_record_hash
    work_order_hash
    candidate_archive_record_hash
    status
    candidate_sufficient
    selection_determinate
    gate_results
    competing_leaf_archive_record_hashes
    contradictions_present
    execution_reopen_count
    completion_loss_count
    company_cautions
    limitations
    readiness_assessment_hash

## 30. Limitations

Every assessment carries the frozen limitations:

    "READY means research-ready for downstream decision analysis, not trading permission"
    "readiness is relative to the supplied validated archive set"
    "contradictions are surfaced but do not automatically block readiness"
    "Tape, playbook, market freshness, and execution conditions are not evaluated"
    "no canonical fork or root is selected"

## 31. Readiness identity

Compute:

    readiness_assessment_hash =
        canonical_hash(
            assessment payload excluding readiness_assessment_hash
        )

The same validated records and candidate hash must produce the same assessment and hash regardless of input record order.

## 32. No ambient time

Increment 11 does not call:

    datetime.now()
    time.time()

It does not decide whether evidence is "fresh enough".

Market freshness requires an explicit future contract, not wall-clock inference.

## 33. No Tape integration

Increment 11 must not import or call:

    TapeAssessment
    assess_tape_state

Tape remains downstream.

## 34. No Playbook integration

Increment 11 must not import or call:

    PlaybookRouting
    route_playbooks

Readiness must not select A-H/NoTrade.

## 35. No Decision Object integration

Increment 11 must not import or call:

    compile_decision

That integration is deferred.

## 36. No filesystem or provider behavior

No:

- archive scanning;
- path construction;
- file writes;
- network;
- provider retrieval;
- external APIs;
- LLM calls.

## 37. No scalar readiness score

Do not add:

    readiness_score
    confidence_score
    completion_percentage
    progress_score

The output is a gate vector plus one categorical state.

## 38. Determinism

For any permutation of the same supplied valid record set:

    assess_research_decision_readiness(
        permutation,
        candidate_hash,
    )

must return exactly the same assessment and hash.

## 39. Candidate not found

If candidate hash is absent:

    raise ValueError(
        "research decision readiness candidate is not present"
    )

No nearest/latest fallback is allowed.

## 40. Progression semantic authority

Increment 11 must call the public Increment 10 evaluator:

    evaluate_research_progression

It must not reconstruct parent/fork/orphan semantics independently.

Increment 10 remains the authority for progression.

## 41. Snapshot matching

The candidate snapshot must be found exactly once in:

    report.snapshots

Otherwise raise ValueError for inconsistent progression output.

## 42. Trajectory matching

The candidate leaf must correspond to exactly one trajectory whose:

    leaf_archive_record_hash == candidate_hash

if it is a leaf.

If zero or multiple matching trajectories exist for a leaf:

    raise ValueError

This is an internal progression-consistency failure.

For a non-leaf candidate, trajectory history fields are:

    execution_reopen_count = 0
    completion_loss_count = 0

and local sufficiency already fails CANDIDATE_IS_LEAF.

## 43. Status precedence

Derive status exactly:

    if any local sufficiency gate fails:
        NOT_READY
    elif any determinacy gate fails:
        INDETERMINATE
    else:
        READY

No other precedence is allowed.

## 44. Examples

### A. COMPLETE + CLOSED + unique complete lineage

    local gates: all pass
    lineage: complete
    leaves: only selected candidate

Result:

    READY

### B. COMPLETE + OPEN

    DOSSIER_COMPLETE: pass
    EXECUTION_CLOSED: fail

Result:

    NOT_READY

### C. CLOSED + insufficient evidence

    DOSSIER_COMPLETE: fail

Result:

    NOT_READY

### D. COMPLETE + CLOSED + unresolved finding

    NO_UNRESOLVED_FINDINGS: fail

Result:

    NOT_READY

### E. COMPLETE + CLOSED + contradiction only

    contradictions_present: True
    all gates pass

Result:

    READY

with contradiction surfaced.

### F. Locally sufficient orphan leaf

    local gates: pass
    LINEAGE_COMPLETE: fail

Result:

    INDETERMINATE

### G. Locally sufficient candidate with sibling leaf

    local gates: pass
    UNIQUE_OBSERVED_LEAF: fail

Result:

    INDETERMINATE

No sibling is selected or ranked.

## 45. Public API

Export from decision_lab:

    ResearchDecisionReadinessAssessment
    ResearchDecisionReadinessCompanyCaution
    ResearchDecisionReadinessGate
    ResearchDecisionReadinessGateResult
    ResearchDecisionReadinessStatus
    assess_research_decision_readiness

No existing Increment 8-10 public API is removed or changed.

## 46. Expected implementation surface

    src/decision_lab/research_decision_readiness.py
    src/decision_lab/__init__.py
    tests/test_research_decision_readiness.py
    docs/superpowers/specs/2026-09-24-research-decision-readiness-design.md
    docs/superpowers/plans/2026-09-24-research-decision-readiness.md

Existing behavior in:

    research_execution.py
    research_execution_archive.py
    research_progression.py
    tape.py
    playbooks.py
    decision.py

must remain unchanged.

## 47. Core test matrix

Minimum required tests:

1. candidate absent is rejected;
2. input permutation yields identical assessment/hash;
3. non-leaf candidate is NOT_READY;
4. COMPLETE + OPEN is NOT_READY;
5. CLOSED + incomplete coverage is NOT_READY;
6. COMPLETE + CLOSED + unresolved finding is NOT_READY;
7. source deficit blocks readiness;
8. company source deficit blocks readiness;
9. contradictions alone do not block readiness;
10. locally sufficient orphan is INDETERMINATE;
11. locally sufficient candidate with competing leaf is INDETERMINATE;
12. unique complete lineage + COMPLETE + CLOSED is READY;
13. local insufficiency takes precedence over branch indeterminacy;
14. competing leaves are surfaced and sorted;
15. historical reopen count is surfaced but not a blocker;
16. historical completion-loss count is surfaced but not a blocker;
17. company cautions are preserved and sorted;
18. fixed gate order is stable;
19. fixed policy version/hash is stable;
20. no scalar score field exists;
21. no Tape/Playbook/Decision dependency exists;
22. Increment 8-10 public exports remain available;
23. Increment 11 public exports are available.

## 48. TDD requirement

Each implementation task must preserve real Native RED -> GREEN history.

No fake failures.

## 49. Review requirement

Before merge:

- exact-final-head pytest passes;
- changed Python files pass Ruff;
- whole-branch review checks semantic boundaries;
- no temporary workflow remains;
- no deferred minor unless explicitly documented;
- self-review is labeled if no independent reviewer is available.

## 50. Completion criterion

Increment 11 is complete when the repository can deterministically distinguish:

    NOT_READY
    INDETERMINATE
    READY

for an explicitly selected research archive leaf, while preserving:

- frozen WorkOrder authority;
- progression lineage;
- fork/orphan ambiguity;
- closure/completion separation;
- unresolved findings;
- independent-source deficits;
- contradiction visibility;
- no trading permission;
- no canonical branch selection;
- no Tape/Playbook/Decision coupling.
