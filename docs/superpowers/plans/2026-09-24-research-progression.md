# Increment 10 — Research Progression Evaluation Implementation Plan

Date: 2026-09-24
Repository: theme-radar-decision-lab
Branch: feature/research-progression
Design: docs/superpowers/specs/2026-09-24-research-progression-design.md

## Goal

Implement a pure deterministic evaluator over immutable ResearchDossierArchiveRecord objects.

The evaluator reconstructs observed lineage, detects roots/forks/orphans/leaves, derives non-monotonic semantic transitions, constructs maximal observed trajectories, computes distinct execution-closure and COMPLETE-coverage timing, and exposes unresolved burden as a vector.

It must not scan archives, mutate history, choose a canonical fork, or make Decision Readiness judgments.

## Expected final changed files

    docs/superpowers/specs/2026-09-24-research-progression-design.md
    docs/superpowers/plans/2026-09-24-research-progression.md
    src/decision_lab/research_progression.py
    src/decision_lab/__init__.py
    tests/test_research_progression.py

Do not modify research_execution.py or research_execution_archive.py unless a blocking semantic defect is independently demonstrated.

## Architecture

One new module:

    src/decision_lab/research_progression.py

It may reuse package-internal pure validators/parsers from research_execution_archive.py.

It must not add filesystem I/O.

Primary API:

    evaluate_research_progression(
        records: Sequence[ResearchDossierArchiveRecord],
    ) -> ResearchProgressionReport

## Task 1 — Graph contract and deterministic report identity

### RED tests

Create tests/test_research_progression.py with focused builders that reuse public Research Execution + Archive APIs to create valid archive records.

Add tests for:

- empty input rejected;
- duplicate archive hash rejected;
- mixed exact WorkOrder archive identity rejected;
- tampered archive record rejected by progression evaluator;
- single root is both root and leaf;
- resolved linear parent chain reconstructs parent/child;
- missing parent is an orphan, not a root;
- fork detected with deterministically sorted children;
- resolved parent evidence_as_of must be strictly earlier;
- permutation of the same input produces equal report and equal progression_report_hash.

Commit the tests alone.

Run CI and retain the intended RED evidence.

### GREEN implementation

Add research_progression.py with the minimal public dataclasses/enums needed for:

    ResearchProgressionOrphan
    ResearchProgressionFork
    ResearchProgressionSnapshot
    ResearchProgressionReport

Implement:

- non-empty validation;
- Increment 9 record semantic validation;
- exact WorkOrder archive equality;
- duplicate identity rejection;
- node map;
- resolved parent map;
- child map;
- temporal validation;
- root/orphan/fork/leaf derivation;
- deterministic snapshot order;
- deterministic report hash.

Do not implement transition details or trajectory timing yet beyond placeholders only if structurally required.

Commit implementation.

Run CI to GREEN.

## Task 2 — Edge-level semantic transitions and unresolved burden

### RED tests

Add tests for:

- OPEN -> CLOSED;
- CLOSED -> OPEN;
- COMPLETE independent from CLOSED;
- COMPLETE -> non-COMPLETE allowed;
- newly satisfied requirements;
- newly unsatisfied requirements after evidence retraction;
- still satisfied/unsatisfied partitions;
- added/removed evidence source hashes;
- added/removed findings;
- same finding_id with changed content appears in changed_finding_ids;
- contradiction false -> true is reported;
- unresolved false -> true is reported;
- global independent-source deficit;
- per-company independent-source deficit;
- company cautions/linkage status preserved;
- no scalar progress or burden score field.

Commit tests alone and retain RED CI.

### GREEN implementation

Add:

    ResearchExecutionClosureTransition
    ResearchCompanyBurden
    ResearchUnresolvedBurden
    ResearchProgressionTransition

Implement one pure transition builder per resolved edge.

Requirements must come only from the frozen WorkOrder universe.

Evidence identity uses source_hash.

Finding identity uses finding_id; same-ID unequal content is "changed".

Build one burden vector per snapshot.

Do not assign positive/negative interpretation to contradiction or unresolved changes.

Commit and run CI to GREEN.

## Task 3 — Maximal trajectories and timing

### RED tests

Add tests for:

- linear root-to-leaf trajectory;
- fork yields one maximal trajectory per leaf;
- multiple roots remain separate;
- orphan begins an incomplete trajectory boundary;
- root-start trajectory computes first execution CLOSED time from source_cycle_as_of;
- root-start trajectory computes first COMPLETE time separately;
- no CLOSED yields None closure timing;
- no COMPLETE yields None completion timing;
- orphan-start trajectory returns None for source-to-first timing;
- CLOSED -> OPEN increments execution_reopen_count;
- COMPLETE -> non-COMPLETE increments completion_loss_count;
- input order cannot change trajectory ordering or report hash.

Commit tests alone and retain RED CI.

### GREEN implementation

Add:

    ResearchProgressionTrajectory

Construct maximal paths from every root and orphan boundary to every reachable leaf.

At forks, branch recursively/iteratively without selecting a winner.

Use existing UTC interpretation semantics.

Compute:

    first_execution_closed_at
    first_complete_at
    time_from_source_to_first_execution_closure_seconds
    time_from_source_to_first_complete_seconds
    execution_reopen_count
    completion_loss_count

Only root-start trajectories may claim source-to-first timing.

Commit and run CI to GREEN.

## Task 4 — Public API and contract regression

### RED tests

Add tests that public imports are available from decision_lab.

Add regression assertions that existing Increment 9 public APIs remain available.

Add tests that research_progression contains no path scanning/write API and that evaluation does not depend on input ordering.

Commit tests alone and retain RED CI if exports are not yet present.

### GREEN implementation

Update src/decision_lab/__init__.py to export only the approved Increment 10 public surface.

Do not change existing export behavior.

Commit and run CI to GREEN.

## Task 5 — Whole-branch hostile self-review and final exact-head qualification

Review the entire branch against the design, not only final tests.

Explicitly inspect for:

- accidental canonical branch selection;
- treating evidence_as_of sort order as lineage;
- treating CLOSED as COMPLETE;
- treating COMPLETE as permanent;
- rejecting valid retraction/regression;
- silently dropping orphans;
- turning missing parents into roots;
- mixed WorkOrder leakage;
- scalar progress/burden scoring;
- unstable ordering;
- ambient time;
- filesystem/archive scanning;
- Tape/Playbook/Decision Readiness leakage;
- changed Increment 9 semantics;
- overclaiming archive integrity as evidence truth.

If a real defect is found:

    add reproducing RED test
      -> commit
      -> fix
      -> commit
      -> GREEN

Final qualification:

1. exact-final-head pytest -q;
2. changed-files Ruff on final Python tree;
3. confirm final changed files match expected surface;
4. confirm no temporary workflow remains;
5. confirm no network/provider dependency;
6. confirm no deferred minor;
7. record self-review limitation if no independent reviewer exists.

## Merge gate

Keep PR draft until all tasks and final review are complete.

Merge only after:

- exact final head is known;
- exact-head CI is green;
- changed-files Ruff is green;
- whole-branch review is complete;
- PR remains mergeable;
- user explicitly authorizes merge.

Preferred merge method remains squash unless repository state requires otherwise.
