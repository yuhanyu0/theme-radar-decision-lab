# Increment 12 — Research-Gated Decision Integration Implementation Plan

Date: 2026-09-25
Repository: theme-radar-decision-lab
Branch: feature/research-gated-decision-integration
Design: docs/superpowers/specs/2026-09-25-research-gated-decision-integration-design.md

## Goal

Create an auditable composition path from validated research readiness to Tape-bound playbook routing and, only when research scope is admitted, to the existing immutable Decision Object.

Keep research sufficiency, market action, and brokerage execution separate.

## Expected final changed files

    docs/superpowers/specs/2026-09-25-research-gated-decision-integration-design.md
    docs/superpowers/plans/2026-09-25-research-gated-decision-integration.md
    src/decision_lab/decision.py
    src/decision_lab/decision_integration.py
    src/decision_lab/__init__.py
    tests/test_decision_integration.py

## Task 1 — Reproducible legacy Decision timestamp + Tape-bound routing provenance

### RED

Create tests/test_decision_integration.py.

Add tests for:

- compile_decision accepts an explicit created_at and preserves it exactly;
- legacy default compile_decision call remains supported;
- DecisionRoutingInputs does not expose tape_state/tape_stage;
- evaluate_research_decision_integration internally routes from TapeAssessment.state/stage;
- routing result equals direct route_playbooks for the same explicit inputs;
- tape/routing-input/routing hashes are deterministic.

Commit tests alone and retain intended RED CI.

### GREEN

Backward-compatibly add optional created_at to compile_decision.

Add decision_integration.py with:

    DecisionRoutingInputs
    ResearchDecisionAdmissionStatus
    ResearchDecisionIntegration
    evaluate_research_decision_integration

At this task, admission mapping may implement readiness status only; scope mismatch details may be completed in Task 2.

Commit and run CI GREEN.

## Task 2 — Research scope binding

### RED

Add tests for:

- NOT_READY -> RESEARCH_NOT_READY;
- INDETERMINATE -> RESEARCH_INDETERMINATE;
- READY THEME_REASSESSMENT -> RESEARCH_SCOPE_MISMATCH;
- wrong theme -> RESEARCH_SCOPE_MISMATCH;
- wrong ticker -> RESEARCH_SCOPE_MISMATCH;
- matching READY COMPANY_DEEP_DIVE -> ADMITTED;
- deterministic fixed-order mismatch reasons;
- non-admitted integrations still surface market_action but admitted_action=None.

Commit and retain RED CI.

### GREEN

Implement exact WorkOrder binding:

    COMPANY_DEEP_DIVE required
    theme exact match
    ticker exact frozen target match

Do not mutate readiness or playbook semantics.

Commit and run CI GREEN.

## Task 3 — Gated Decision Object compilation and deterministic envelope

### RED

Add tests for:

- invalid/blank compile-request identity fields rejected;
- non-admitted -> decision=None;
- admitted + market BLOCKED -> decision action BLOCKED;
- admitted + WATCH_ONLY -> WATCH_ONLY;
- admitted + BUILD_ON_RETEST -> BUILD_ON_RETEST;
- explicit created_at makes repeated compile output identical;
- envelope contains exact readiness/integration provenance;
- envelope hash deterministic;
- research record permutation produces equal envelope.

Commit and retain RED CI.

### GREEN

Add:

    ResearchGatedDecisionCompileRequest
    ResearchGatedDecisionEnvelope
    compile_research_gated_decision

Call existing compile_decision only when admission_status == ADMITTED.

Pass integration.tape and integration.routing directly.

No action rewrite.

Commit and run CI GREEN.

## Task 4 — Public API and regression boundary

### RED

Add tests for Increment 12 public exports and retention of Increment 9-11 exports.

Assert decision_integration has no writer, broker, network, scan, or ambient-time surface.

Commit and retain RED CI.

### GREEN

Update src/decision_lab/__init__.py only.

Commit and run CI GREEN.

## Task 5 — Whole-branch hostile self-review and final qualification

Review for:

- READY treated as market action;
- market BLOCKED confused with research blocking;
- theme research admitted for ticker decision;
- theme/ticker mismatch silently tolerated;
- routing accepted independently of Tape;
- action rewritten after route_playbooks;
- direct branch/leaf selection;
- use of current wall clock inside decision_integration;
- duplicate readiness or routing semantics;
- brokerage behavior;
- schema mutation;
- legacy compile_decision behavior breakage.

If a real defect is found:

    reproducing RED test
      -> commit
      -> fix
      -> commit
      -> GREEN

Final gates:

1. exact-final-head pytest -q;
2. Ruff on changed Python files;
3. exact 6-file final surface;
4. no temporary lint workflow;
5. whole-branch self-review documented;
6. no deferred minor unless explicit.

## Merge gate

Keep PR draft until Task 5 is complete.

Preferred merge remains squash with expected-head SHA lock after explicit user authorization.
