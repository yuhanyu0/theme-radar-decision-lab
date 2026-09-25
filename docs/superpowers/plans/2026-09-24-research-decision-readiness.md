# Increment 11 — Research Decision Readiness Implementation Plan

Date: 2026-09-24
Repository: theme-radar-decision-lab
Branch: feature/research-decision-readiness
Design: docs/superpowers/specs/2026-09-24-research-decision-readiness-design.md

## Goal

Implement a pure deterministic research-readiness gate over validated Research Dossier archives and Increment 10 progression semantics.

READY means only:

    research-ready for downstream decision analysis

It never means trading permission.

## Expected final changed files

    docs/superpowers/specs/2026-09-24-research-decision-readiness-design.md
    docs/superpowers/plans/2026-09-24-research-decision-readiness.md
    src/decision_lab/research_decision_readiness.py
    src/decision_lab/__init__.py
    tests/test_research_decision_readiness.py

Do not modify research_execution.py, research_execution_archive.py, research_progression.py, tape.py, playbooks.py, or decision.py.

## Task 1 — Candidate binding and categorical readiness gates

### RED

Create tests/test_research_decision_readiness.py using public Research Execution / Archive builders.

Add tests for:

- absent candidate rejected;
- non-leaf candidate -> NOT_READY;
- COMPLETE + OPEN -> NOT_READY;
- CLOSED + incomplete coverage -> NOT_READY;
- unique complete lineage + COMPLETE + CLOSED -> READY;
- fixed gate order;
- no scalar score field;
- input permutation determinism.

Commit tests alone and retain intended RED CI.

### GREEN

Add:

    src/decision_lab/research_decision_readiness.py

Implement:

    ResearchDecisionReadinessStatus
    ResearchDecisionReadinessGate
    ResearchDecisionReadinessGateResult
    ResearchDecisionReadinessAssessment
    assess_research_decision_readiness

Call evaluate_research_progression(records) rather than duplicating graph logic.

Add fixed policy version/hash and deterministic assessment hash.

Commit and run CI to GREEN.

## Task 2 — Unresolved/source gates and determinacy semantics

### RED

Add tests for:

- unresolved finding blocks;
- global source deficit blocks;
- company source deficit blocks;
- contradiction alone does not block;
- locally sufficient orphan -> INDETERMINATE;
- locally sufficient candidate with competing leaf -> INDETERMINATE;
- local insufficiency overrides branch ambiguity;
- competing leaves surfaced deterministically.

Commit tests alone and retain RED CI.

### GREEN

Implement the remaining local and determinacy gates.

Status precedence must be:

    local failure -> NOT_READY
    else determinacy failure -> INDETERMINATE
    else READY

Do not add a branch resolver.

Commit and run CI to GREEN.

## Task 3 — Historical cautions and company caution preservation

### RED

Add tests for:

- prior CLOSED -> OPEN count surfaced;
- prior COMPLETE -> non-COMPLETE count surfaced;
- neither historical event automatically blocks current READY;
- company cautions are preserved and sorted;
- contradiction visibility is preserved;
- limitations state that READY is not trading permission.

Commit tests alone and retain RED CI.

### GREEN

Add:

    ResearchDecisionReadinessCompanyCaution

Bind history fields from the unique candidate trajectory.

Preserve company caution text without turning it into a new hidden gate.

Commit and run CI to GREEN.

## Task 4 — Public API and regression boundary

### RED

Add tests for Increment 11 exports from decision_lab and retention of existing Increment 8-10 exports.

Assert the module has no Tape, Playbook, Decision, scan, write, provider, network, or ambient-time API surface.

Commit tests alone and retain RED CI.

### GREEN

Update src/decision_lab/__init__.py with only the approved public Increment 11 surface.

Commit and run CI to GREEN.

## Task 5 — Whole-branch hostile self-review and final qualification

Review for:

- accidental latest/earliest candidate selection;
- hidden fork resolution;
- treating READY as trade permission;
- treating contradiction as automatic failure;
- treating company linkage as mandatory when WorkOrder does not;
- treating COMPLETE as CLOSED;
- ignoring unresolved findings;
- orphan promoted to READY;
- competing leaves promoted to READY;
- scalar readiness score;
- Tape/Playbook/Decision coupling;
- filesystem/network/provider calls;
- ambient wall-clock semantics;
- duplicated progression logic;
- changed Increment 8-10 behavior.

If a defect is found:

    reproducing RED test
      -> commit
      -> fix
      -> commit
      -> GREEN

Final qualification:

1. exact-final-head pytest -q;
2. changed-files Ruff on final Python tree;
3. confirm exact 5-file surface;
4. confirm no temporary workflow;
5. confirm no network/provider/ambient time;
6. record self-review limitation if no independent reviewer exists.

## Merge gate

Keep PR draft until the full Increment 11 gate is complete.

Preferred merge method: squash with expected-head SHA lock after explicit user authorization.
