# Increment 12 — Research-Gated Decision Integration Implementation Plan

Date: 2026-09-24
Repository: theme-radar-decision-lab
Branch: feature/research-decision-integration
Design: docs/superpowers/specs/2026-09-24-research-decision-integration-design.md

## Goal

Add a new integration path that binds one exact validated research-readiness state to one exact company target, then uses the existing Tape, Playbook Router, and Decision compiler without changing their semantics.

## Expected final changed files

    docs/superpowers/specs/2026-09-24-research-decision-integration-design.md
    docs/superpowers/plans/2026-09-24-research-decision-integration.md
    src/decision_lab/research_decision_integration.py
    src/decision_lab/__init__.py
    tests/test_research_decision_integration.py

Do not modify:

    research_execution.py
    research_execution_archive.py
    research_progression.py
    research_decision_readiness.py
    tape.py
    playbooks.py
    decision.py

## Task 1 — Deterministic admission and provenance binding

### RED

Create tests/test_research_decision_integration.py.

Reuse public Research Execution / Archive / Readiness builders.

Add tests for:

- stale or mismatched readiness rejected;
- old READY rejected after supplied history gains competing leaf;
- THEME_REASSESSMENT readiness rejected for ticker Decision admission;
- non-target ticker rejected;
- ticker normalization;
- READY company-deep-dive target -> ADMITTED;
- NOT_READY -> BLOCKED_NOT_READY;
- INDETERMINATE -> BLOCKED_INDETERMINATE;
- record permutation produces identical admission/hash;
- no auto target selection.

Commit tests alone and retain intended RED CI.

### GREEN

Add:

    src/decision_lab/research_decision_integration.py

Implement:

    ResearchDecisionAdmissionStatus
    ResearchDecisionAdmission
    evaluate_research_decision_admission

Rules:

- recompute readiness with public Increment 11 evaluator;
- require exact equality with supplied readiness;
- bind to exact candidate archive;
- require COMPANY_DEEP_DIVE;
- derive theme from WorkOrder;
- require explicit ticker in WorkOrder targets;
- derive categorical admission;
- canonical admission hash.

No Tape, Playbook, or Decision call yet.

Commit and run CI to GREEN.

## Task 2 — Exact Tape/Router/Decision composition

### RED

Add:

    ResearchDecisionRoutingInputs

Tests:

- blocked admission cannot compile;
- route is derived from exact Tape.state/stage;
- one exact theme_key is shared between router and Decision Object;
- one exact world_confidence is shared between router and Decision Object;
- READY + Theme key off preserves WATCH_ONLY;
- READY + falling-knife Tape preserves BLOCKED;
- READY + clean-retest B3 preserves router action;
- direct route_playbooks() result equals integration routing under identical inputs;
- decision theme/ticker come from admission binding, not caller parameters.

Commit tests alone and retain RED CI.

### GREEN

Implement:

    compile_research_gated_decision(...)

Flow:

    admission = evaluate_research_decision_admission(...)
    require admission.status == ADMITTED
    routing = route_playbooks(
        theme_key=theme_key,
        tape_state=tape.state,
        tape_stage=tape.stage,
        ... routing_inputs ...
    )
    decision = compile_decision(
        theme=admission.theme_id,
        ticker=admission.ticker,
        theme_key=theme_key,
        tape=tape,
        routing=routing,
        world_confidence=routing_inputs.world_confidence,
        ... existing decision args ...
    )

Do not modify route_playbooks or compile_decision.

Commit and run CI to GREEN.

## Task 3 — Auditable compilation record

### RED

Add tests for:

- ResearchGatedDecisionCompilation contains exact admission;
- readiness hash and candidate/work-order provenance are preserved;
- Tape object is preserved;
- routing object is preserved exactly;
- child Decision Object equals direct compile semantics for the same event inputs except for event timestamp identity constraints;
- child action equals routing.action;
- strongest_reason_not_to_trade is preserved;
- compilation_hash recomputes over all exact child components;
- no ledger file is written as a side effect;
- no false deterministic guarantee across separate compilation events.

Commit tests alone and retain RED CI.

### GREEN

Add:

    ResearchGatedDecisionCompilation

Compute canonical compilation hash over:

    admission
    readiness identity
    Tape
    routing
    exact child Decision Object

Document in code that admission is deterministic while compilation is eventful because child compile_decision sets created_at.

Commit and run CI to GREEN.

## Task 4 — Public API and regression boundary

### RED

Add tests for Increment 12 public exports and retention of existing Increment 8-11 exports.

Assert module surface has no:

    broker
    order submission
    write_immutable_json
    ledger/live writer
    OHLCV Tape assessment
    provider/network API
    scalar combined score

Commit tests alone and retain RED CI.

### GREEN

Update src/decision_lab/__init__.py with only approved Increment 12 exports.

Commit and run CI to GREEN.

## Task 5 — Whole-branch hostile review and final qualification

Review for:

- stale readiness acceptance;
- cross-theme leakage;
- cross-ticker leakage;
- theme-level readiness authorizing company target;
- hidden candidate or target selection;
- caller-supplied routing detached from Tape;
- duplicate/inconsistent theme key;
- duplicate/inconsistent world confidence;
- research readiness changing Playbook scores or action;
- blocked research state reaching compile_decision;
- Tape reimplementation;
- invented freshness rules;
- combined scalar score;
- ledger write side effect;
- broker/network side effect;
- changed existing modules.

If a real defect is found:

    reproducing RED test
      -> commit
      -> fix
      -> commit
      -> GREEN

Final qualification:

1. exact-final-head pytest -q;
2. changed-files Ruff on final Python tree;
3. final changed files exactly equal planned 5-file surface;
4. no temporary workflow remains;
5. whole-branch self-review recorded honestly if no independent reviewer exists.

## Merge gate

Keep PR draft until all tasks pass.

Merge only after explicit user authorization.

Preferred merge:

    squash
    + expected-head SHA lock
    + post-merge main CI verification.
