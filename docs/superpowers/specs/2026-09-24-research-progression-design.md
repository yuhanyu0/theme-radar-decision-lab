# Increment 10 — Research Progression Evaluation Design

Date: 2026-09-24
Status: approved in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: feature/research-progression

## 1. Purpose

Interpret the immutable ResearchDossierArchiveRecord history created by Increment 9 without mutating that history and without yet making a Decision Readiness judgment.

Target chain:

    Sequence[ResearchDossierArchiveRecord]
      -> lineage reconstruction
      -> edge-level semantic transitions
      -> root/orphan/fork/leaf detection
      -> maximal observed trajectories
      -> closure/completion timing
      -> unresolved-burden snapshots
      -> ResearchProgressionReport

Increment 10 answers:

    what changed across research snapshots?

It does not answer:

    should a decision be taken now?

That remains a later increment.

## 2. Scientific role

Increment 9 established an immutable epistemic history:

    archive chronology
      != successful research

    parent relation
      != monotonic improvement

    COMPLETE
      != permanent closure

    archive integrity
      != raw evidence truth

Increment 10 is the first layer that interprets change across those historical states.

Its central invariants are:

    archive chronology != research progress
    parenthood != improvement
    execution closure != requirement completion
    closure != permanence
    more evidence != less uncertainty
    later snapshot != better snapshot

The evaluator must therefore report transitions rather than compressing them into a single progress score.

## 3. Selected architecture

Add one focused module:

    src/decision_lab/research_progression.py

Primary public entry point:

    evaluate_research_progression(
        records: Sequence[ResearchDossierArchiveRecord],
    ) -> ResearchProgressionReport

The function is pure and deterministic.

It performs no filesystem scan, no network access, no provider access, no wall-clock read, and no mutation.

Increment 9 archive behavior remains unchanged.

## 4. Explicit non-goals

Increment 10 does not add:

- archive directory scanning;
- archive index or manifest;
- canonical branch selection;
- fork resolution;
- orphan repair;
- archive mutation;
- a scalar research-progress score;
- a scalar unresolved-burden score;
- Decision Readiness;
- Tape assessment;
- playbook routing;
- Decision Object compilation;
- trading permission;
- price/outcome evaluation;
- research-value estimation;
- attention allocation;
- provider retrieval;
- LLM execution;
- ambient semantic time.

## 5. Input contract

Input is:

    Sequence[ResearchDossierArchiveRecord]

The sequence must be non-empty.

Input order has no semantic meaning.

The evaluator sorts and derives all output deterministically.

Every input record must independently satisfy the existing Increment 9 dossier-archive semantic validator.

The evaluator may reuse the package-internal Increment 9 validator. It must not weaken or duplicate archive semantics.

## 6. One WorkOrder per evaluation

All records in one evaluation must belong to the same exact WorkOrder archive identity.

Require equality of:

    record.work_order_archive.archive_record_hash

across all input records.

Also require the embedded ResearchWorkOrderArchiveRecord objects to be equal.

This is stronger than matching only work_order_hash.

Why:

- requirement transitions are meaningful only under one frozen requirement set;
- source lineage must remain fixed;
- policy must remain fixed;
- a new WorkOrder is a new research task, not the next snapshot of the old task.

Mixed WorkOrders raise ValueError.

## 7. Duplicate input

archive_record_hash is the node identity.

Duplicate archive_record_hash values in the input are rejected.

The evaluator must never interpret duplicated sequence entries as repeated research activity.

## 8. Graph model

Each dossier archive record is one node.

A node has at most one declared parent:

    prior_dossier_archive_record_hash

A resolved edge exists when the declared parent hash is present in the input set.

Therefore the observed structure is a directed forest with possible:

- roots;
- forks;
- leaves;
- orphans caused by incomplete input coverage.

No node receives a synthetic parent.

## 9. Root

A root is a node whose:

    prior_dossier_archive_record_hash is None

Roots are explicit historical starts.

A node with a missing declared parent is not a root.

## 10. Orphan

An orphan is a node whose:

    prior_dossier_archive_record_hash is not None

but whose referenced parent archive hash is absent from the supplied input.

Orphans are reported, not rejected.

Reason:

Increment 9 intentionally permits standalone reading of a child archive without requiring the parent file.

Increment 10 must therefore support incomplete archive subsets.

## 11. Resolved-parent temporal validation

For every resolved parent -> child edge:

    parent.evidence_as_of < child.evidence_as_of

must hold strictly.

If not, raise ValueError.

This re-establishes the temporal condition at the graph level when both records are available.

Path order, input order, filesystem modification time, and lexical hash order are never used as progression relations.

## 12. Fork

A fork exists when one resolved parent has more than one child in the supplied set.

Represent it explicitly with:

    ResearchProgressionFork(
        parent_archive_record_hash,
        child_archive_record_hashes,
    )

Children are sorted deterministically.

A fork is not an error.

Increment 10 does not select a preferred child.

## 13. Leaf

A leaf is any supplied node with no resolved children in the supplied set.

An orphan may also be a leaf.

A root may also be a leaf.

## 14. No canonical branch

Increment 10 must not infer a canonical trajectory.

It reports every maximal observed trajectory.

No trajectory receives a ranking, score, probability, or preferred status.

## 15. Maximal observed trajectory

Define:

    ResearchProgressionTrajectory

A trajectory starts at either:

- a root; or
- an orphan boundary.

It follows resolved child links until a leaf.

At a fork, each child produces a separate maximal trajectory.

Shared prefixes may therefore appear in multiple trajectories.

Required fields:

    archive_record_hashes
    start_archive_record_hash
    leaf_archive_record_hash
    starts_at_root
    starts_at_orphan
    lineage_complete
    first_execution_closed_at
    first_complete_at
    time_from_source_to_first_execution_closure_seconds
    time_from_source_to_first_complete_seconds
    execution_reopen_count
    completion_loss_count

For this increment:

    lineage_complete == starts_at_root

because all later links on the trajectory are resolved by construction.

## 16. Execution closure is not completion

Existing dossier semantics distinguish:

    dossier.closure: ResearchExecutionClosure
    dossier.status: ResearchDossierStatus

These must remain separate.

Examples that are valid:

    status == COMPLETE
    closure == OPEN

and:

    status == BLOCKED_INSUFFICIENT_EVIDENCE
    closure == CLOSED

Therefore Increment 10 must never equate CLOSED with COMPLETE.

## 17. Closure transition

For every resolved parent -> child edge, classify the exact execution-closure transition:

    OPEN -> OPEN
    OPEN -> CLOSED
    CLOSED -> OPEN
    CLOSED -> CLOSED

Define:

    ResearchExecutionClosureTransition

with values:

    OPEN_TO_OPEN
    OPEN_TO_CLOSED
    CLOSED_TO_OPEN
    CLOSED_TO_CLOSED

A CLOSED -> OPEN transition is an execution reopening.

It is allowed and reported.

## 18. Completion transition

Requirement coverage completion is represented by:

    ResearchDossierStatus.COMPLETE

The evaluator reports parent and child status directly.

Additionally derive:

    became_complete
    lost_complete_status

where:

    became_complete =
        parent.status is not COMPLETE
        and child.status is COMPLETE

    lost_complete_status =
        parent.status is COMPLETE
        and child.status is not COMPLETE

Loss of COMPLETE is allowed.

Increment 9 already permits evidence retraction and non-monotonic trajectories.

## 19. Requirement transition

Within one WorkOrder the requirement universe is frozen.

Therefore Increment 10 does not invent "new requirement" or "removed requirement" transitions.

For every resolved edge derive:

    newly_satisfied_requirements
    newly_unsatisfied_requirements
    still_satisfied_requirements
    still_unsatisfied_requirements

All values are ResearchRequirement objects from the frozen WorkOrder.

This directly captures both progress and regression.

## 20. Evidence transition

For every resolved edge derive immutable evidence-source changes:

    added_evidence_source_hashes
    removed_evidence_source_hashes

Evidence retraction is therefore first-class and not treated as invalid progression.

No claim is made that more evidence is better.

## 21. Finding transition

For every resolved edge derive:

    added_finding_ids
    removed_finding_ids

Findings are compared by finding_id.

A changed finding with the same finding_id cannot silently be treated as unchanged.

If the same finding_id exists in parent and child with unequal ResearchFinding content, record it in:

    changed_finding_ids

This is descriptive only.

## 22. Contradiction and unresolved transitions

Every edge records:

    contradictions_before
    contradictions_after
    unresolved_before
    unresolved_after

Do not interpret false -> true as research failure.

Discovering a contradiction or unresolved issue may be genuine progress.

## 23. Unresolved burden is a vector, not a score

Define:

    ResearchUnresolvedBurden

for each supplied snapshot.

Required fields:

    archive_record_hash
    unsatisfied_requirements
    unresolved_finding_ids
    contradictions_present
    independent_source_deficit
    company_burdens

where:

    independent_source_deficit =
        max(
            0,
            work_order.minimum_independent_sources
            - dossier.independent_source_count,
        )

Company-level burden is represented by:

    ResearchCompanyBurden(
        ticker,
        independent_source_deficit,
        linkage_status,
        cautions,
    )

with:

    independent_source_deficit =
        max(
            0,
            work_order.minimum_independent_sources_per_company
            - assessment.independent_source_count,
        )

No fields are summed into one burden score.

## 24. Why no scalar progress score

A scalar such as:

    satisfied_requirement_count

would incorrectly equate very different epistemic states.

For example:

- one new contradiction may increase uncertainty while improving knowledge;
- evidence retraction may reduce coverage while correcting a false belief;
- COMPLETE may later be lost;
- a CLOSED run may be blocked rather than successful.

Increment 10 therefore exposes inspectable state transitions and leaves value judgments to later layers.

## 25. Snapshot representation

Define:

    ResearchProgressionSnapshot

Required fields:

    archive_record_hash
    prior_dossier_archive_record_hash
    evidence_as_of
    closure
    status
    burden

Snapshots are sorted by:

    (parsed evidence_as_of, archive_record_hash)

This order is only deterministic presentation order.

It is not a lineage relation.

## 26. Edge representation

Define:

    ResearchProgressionTransition

Required fields:

    parent_archive_record_hash
    child_archive_record_hash
    parent_evidence_as_of
    child_evidence_as_of
    elapsed_seconds
    closure_transition
    parent_status
    child_status
    became_complete
    lost_complete_status
    newly_satisfied_requirements
    newly_unsatisfied_requirements
    still_satisfied_requirements
    still_unsatisfied_requirements
    added_evidence_source_hashes
    removed_evidence_source_hashes
    added_finding_ids
    removed_finding_ids
    changed_finding_ids
    contradictions_before
    contradictions_after
    unresolved_before
    unresolved_after

elapsed_seconds is derived only from the two canonical evidence_as_of timestamps on the resolved edge.

## 27. Timing origin

For complete root-start trajectories, time-to-first metrics use:

    work_order.source_cycle_as_of

as the origin.

This follows the Increment 9 archive design, which groups all later dossier snapshots under the original source cycle specifically to permit later closure analysis.

Use the same UTC interpretation semantics as the existing research archive layer.

## 28. Time to first execution closure

For a lineage-complete trajectory:

    time_from_source_to_first_execution_closure_seconds

is the elapsed time from source_cycle_as_of to the first dossier on that trajectory with:

    closure == CLOSED

If no such dossier exists, the value is None.

For orphan-start trajectories the value is None because the missing prefix prevents a true "first" claim.

## 29. Time to first complete coverage

For a lineage-complete trajectory:

    time_from_source_to_first_complete_seconds

is the elapsed time from source_cycle_as_of to the first dossier on that trajectory with:

    status == COMPLETE

If no such dossier exists, the value is None.

For orphan-start trajectories it is None.

This metric is intentionally distinct from execution closure timing.

## 30. Reopen count

For each maximal trajectory:

    execution_reopen_count

counts resolved transitions:

    CLOSED -> OPEN

on that trajectory.

No assumption is made that reopening is bad.

## 31. Completion loss count

For each maximal trajectory:

    completion_loss_count

counts transitions where:

    parent.status == COMPLETE
    child.status != COMPLETE

This makes non-permanent completion explicit.

## 32. Report identity

Define:

    ResearchProgressionReport

Required fields:

    work_order_archive_record_hash
    work_order_hash
    input_archive_record_hashes
    snapshots
    transitions
    roots
    orphans
    forks
    leaves
    trajectories
    progression_report_hash

input_archive_record_hashes are sorted lexicographically because input sequence order has no meaning.

progression_report_hash is:

    canonical_hash(report payload excluding progression_report_hash)

This gives later increments an exact deterministic identity without persisting a new archive type.

## 33. Determinism

For any permutation of the same valid input record set:

    evaluate_research_progression(permutation)
        == evaluate_research_progression(original)

including the same:

    progression_report_hash

No ambient ordering may leak into output.

## 34. Empty input

Empty input raises ValueError.

There is no meaningful WorkOrder identity to bind a report to.

## 35. Tamper behavior

If any supplied archive record fails the existing Increment 9 semantic validator, evaluation fails.

Increment 10 must not interpret a semantically invalid historical node.

## 36. Hash collision assumptions

The graph uses Increment 9 archive_record_hash as node identity.

The design assumes collision resistance of the existing canonical SHA-256 identity.

Increment 10 does not attempt adversarial hash-collision handling beyond duplicate-identity rejection.

## 37. Orphan timing

An orphan-start trajectory may still expose:

- observed snapshot states;
- resolved transitions after the orphan boundary;
- edge elapsed times;
- reopen counts within the observed suffix;
- completion-loss counts within the observed suffix.

But it must not claim source-to-first closure or source-to-first completion timing.

## 38. Multiple roots

Multiple explicit roots under one WorkOrder are allowed.

They represent separate observed lineages unless later structure says otherwise.

Increment 10 does not collapse them.

## 39. Multiple orphans

Multiple orphan boundaries are allowed.

Each missing parent reference is reported by child hash and missing parent hash.

Define:

    ResearchProgressionOrphan(
        child_archive_record_hash,
        missing_parent_archive_record_hash,
    )

## 40. Fork reporting

Forks are reported independent of trajectories so downstream consumers do not need to infer them from repeated prefixes.

## 41. No archive scanning

The evaluator receives typed records from its caller.

It does not discover files under:

    recomputed/research_execution

Directory scanning remains a separate future layer.

This keeps progression semantics testable without filesystem state.

## 42. No write path

Increment 10 produces no JSON file and no immutable writer.

The report is a deterministic in-memory derived view.

Persistence, if ever needed, is a separate contract.

## 43. Public API

Export from decision_lab:

    ResearchCompanyBurden
    ResearchExecutionClosureTransition
    ResearchProgressionFork
    ResearchProgressionOrphan
    ResearchProgressionReport
    ResearchProgressionSnapshot
    ResearchProgressionTrajectory
    ResearchProgressionTransition
    ResearchUnresolvedBurden
    evaluate_research_progression

No Increment 9 archive export is removed or behaviorally changed.

## 44. Core test matrix

Minimum required tests:

1. empty input rejected;
2. duplicate archive identity rejected;
3. mixed WorkOrder archive identity rejected;
4. semantically invalid archive record rejected;
5. input permutation produces identical report/hash;
6. single root snapshot produces root+leaf and no transition;
7. linear parent chain reconstructs correctly;
8. missing parent is reported as orphan, not root;
9. fork produces one fork record and separate maximal trajectories;
10. resolved parent must be strictly earlier;
11. OPEN -> CLOSED classified correctly;
12. CLOSED -> OPEN classified as reopening;
13. COMPLETE and CLOSED remain independent;
14. COMPLETE -> non-COMPLETE is allowed and counted;
15. satisfied -> unsatisfied requirement regression is reported;
16. unsatisfied -> satisfied transition is reported;
17. added and removed evidence hashes are reported;
18. changed same-ID finding is reported;
19. contradiction false -> true is descriptive, not rejected;
20. unresolved false -> true is descriptive, not rejected;
21. burden exposes independent-source deficit;
22. company burden exposes per-company deficit/cautions/linkage state;
23. no scalar burden/progress score exists;
24. complete-root trajectory gets source-to-first closure timing;
25. complete-root trajectory gets source-to-first COMPLETE timing;
26. orphan trajectory has no source-to-first timing;
27. multiple roots remain separate;
28. public exports are available.

## 45. Regression boundary

The final branch must not modify behavior in:

    research_execution.py
    research_execution_archive.py
    replay/archive/cohort
    scanner/budget
    evidence/adapters/linkage
    tape.py
    playbooks.py
    decision.py
    outcomes.py
    themes.py
    universe.py
    ledger.py

Expected implementation surface:

    src/decision_lab/research_progression.py
    src/decision_lab/__init__.py
    tests/test_research_progression.py
    docs/superpowers/specs/2026-09-24-research-progression-design.md
    docs/superpowers/plans/2026-09-24-research-progression.md

## 46. TDD requirement

Implementation follows Native red -> green history.

Each semantic task must have:

    test commit
      -> CI failure for the intended missing behavior
      -> implementation commit
      -> CI success

Do not fake RED by breaking unrelated code.

## 47. Review requirement

Before merge:

- exact-final-head pytest must pass;
- changed Python files must pass Ruff;
- whole-branch diff must be reviewed against this spec;
- no temporary workflow may remain;
- no deferred known minor should remain unless explicitly documented;
- self-review must be labeled as self-review if no independent reviewer is available.

## 48. Completion criterion

Increment 10 is complete only when the repository can deterministically answer, for one frozen Research WorkOrder:

- what dossier nodes are present;
- how they are related;
- where history is incomplete;
- where forks exist;
- what requirements improved or regressed;
- what evidence/findings were added, removed, or changed;
- whether execution closed or reopened;
- whether COMPLETE coverage was achieved or later lost;
- what unresolved burden is visible at every snapshot;
- how long complete lineages took to first execution closure and first COMPLETE coverage;

without:

- choosing a preferred branch;
- collapsing research into a scalar score;
- changing Increment 9 archive semantics;
- making a Decision Readiness judgment.
