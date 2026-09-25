# Increment 12 — Research-Gated Decision Integration Design

Date: 2026-09-24
Status: approved in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: feature/research-decision-integration

## 1. Purpose

Connect Increment 11 Research Decision Readiness to the existing Tape / Playbook / Decision chain without changing the semantics of any existing layer.

Target chain:

    validated research dossier archives
        -> ResearchDecisionReadinessAssessment
        -> deterministic research-decision admission
        -> existing TapeAssessment
        -> existing route_playbooks(...)
        -> existing compile_decision(...)
        -> ResearchGatedDecisionCompilation

Increment 12 answers:

    may this exact research state authorize compilation of a downstream Decision Object
    for this exact company target?

It does not answer:

    is the thesis true?
    should the system trade?
    should a particular playbook win?
    is the Tape state correct?
    is the market data fresh enough?
    should a broker order be sent?

## 2. Core separation

The system must preserve:

    research sufficiency
        !=
    execution context
        !=
    decision compilation
        !=
    brokerage execution

Research readiness controls admission into decision analysis.

Tape and Playbook retain their existing execution semantics.

Decision compilation remains an immutable analytical record, not an order.

## 3. Selected architecture

Add one focused module:

    src/decision_lab/research_decision_integration.py

Public APIs:

    evaluate_research_decision_admission(
        records,
        readiness,
        ticker,
    ) -> ResearchDecisionAdmission

    compile_research_gated_decision(
        *,
        records,
        readiness,
        ticker,
        tape,
        theme_key,
        routing_inputs,
        decision_id,
        market_asof,
        theme_state,
        company_state,
        strongest_reason_not_to_trade,
        model_version,
        config_payload,
        ... existing optional decision metadata ...
    ) -> ResearchGatedDecisionCompilation

The first API is pure and deterministic.

The second API is intentionally eventful because it delegates to the existing compile_decision(), which stamps created_at from the wall clock.

## 4. Existing-module authority

Increment 12 must not reimplement:

- Research Decision Readiness;
- Research Progression;
- Tape classification;
- Playbook scoring/routing;
- Decision Object compilation.

It must call the existing public functions:

    assess_research_decision_readiness(...)
    route_playbooks(...)
    compile_decision(...)

and preserve their returned semantics.

## 5. No changes to existing behavior

Do not modify behavior in:

    research_execution.py
    research_execution_archive.py
    research_progression.py
    research_decision_readiness.py
    tape.py
    playbooks.py
    decision.py

Increment 12 adds a new integration path around those modules.

Existing direct callers remain valid and unchanged.

## 6. Why a separate integration module

Do not add research-specific logic directly to route_playbooks().

Do not add a readiness argument directly to compile_decision().

Those functions already have established meanings.

Research gating is a distinct cross-layer composition concern and therefore belongs in a new module.

## 7. Admission status

Define:

    class ResearchDecisionAdmissionStatus(str, Enum):
        ADMITTED = "ADMITTED"
        BLOCKED_NOT_READY = "BLOCKED_NOT_READY"
        BLOCKED_INDETERMINATE = "BLOCKED_INDETERMINATE"

There is no generic score.

## 8. Readiness is explicit input

evaluate_research_decision_admission requires an explicit:

    ResearchDecisionReadinessAssessment

The integration layer must not silently choose or construct a candidate from "latest", "best", "lowest burden", or any other heuristic.

The readiness object already carries the explicit candidate archive identity.

## 9. Readiness must be revalidated against supplied records

The supplied readiness object is not trusted merely because its status field says READY.

The admission evaluator must recompute:

    expected = assess_research_decision_readiness(
        records,
        readiness.candidate_archive_record_hash,
    )

and require:

    readiness == expected

If not, raise ValueError.

This detects:

- stale readiness after new archive nodes appear;
- a readiness object from another record set;
- altered readiness fields;
- READY computed before a later competing leaf appeared.

## 10. Candidate archive binding

The readiness candidate hash must identify exactly one supplied ResearchDossierArchiveRecord after Increment 11 validation.

The integration layer derives the candidate WorkOrder from that exact record.

No nearest/latest fallback exists.

## 11. Company-deep-dive requirement

A ticker-specific Decision Object must be authorized by a:

    ResearchMode.COMPANY_DEEP_DIVE

WorkOrder.

A THEME_REASSESSMENT readiness assessment is not sufficient to authorize a ticker-specific Decision Object.

If the candidate WorkOrder mode is not COMPANY_DEEP_DIVE:

    raise ValueError

Reason:

theme-level sufficiency must not silently authorize arbitrary company decisions.

## 12. Exact theme binding

The downstream decision theme is not supplied independently.

It is derived from:

    candidate.work_order_archive.work_order.theme_id

This prevents Theme A readiness from being attached to a Theme B Decision Object.

## 13. Explicit ticker binding

The caller must explicitly supply:

    ticker

The ticker is normalized to uppercase.

It must appear exactly in the frozen WorkOrder target ticker set.

If not:

    raise ValueError

No first-target or single-target fallback is allowed.

## 14. Multi-target WorkOrders

A COMPANY_DEEP_DIVE WorkOrder may contain multiple targets.

Increment 12 may admit a decision for any explicitly requested ticker that is an exact WorkOrder target.

The integration layer must never auto-select among targets.

## 15. Admission record

Define:

    ResearchDecisionAdmission

Required fields:

    readiness_assessment_hash
    readiness_policy_hash
    progression_report_hash
    work_order_archive_record_hash
    work_order_hash
    candidate_archive_record_hash
    theme_id
    ticker
    status
    reasons
    admission_hash

## 16. Admission reasons

Reasons are categorical, deterministic text constants.

Minimum reason behavior:

ADMITTED:
    "research readiness is READY and target binding is exact"

BLOCKED_NOT_READY:
    "research readiness is NOT_READY"

BLOCKED_INDETERMINATE:
    "research readiness is INDETERMINATE"

No natural-language model generation.

## 17. Admission status law

After exact record/readiness/target binding:

    if readiness.status == NOT_READY:
        BLOCKED_NOT_READY
    elif readiness.status == INDETERMINATE:
        BLOCKED_INDETERMINATE
    elif readiness.status == READY:
        ADMITTED
    else:
        raise ValueError

## 18. Admission identity

Compute:

    admission_hash =
        canonical_hash(
            admission payload excluding admission_hash
        )

For the same valid records, readiness, and ticker:

    evaluate_research_decision_admission(...)

must be deterministic and independent of input record ordering.

## 19. No routing on blocked admission

compile_research_gated_decision must evaluate admission first.

If status is not ADMITTED:

    raise ValueError

It must not call route_playbooks() and must not call compile_decision().

A blocked research state cannot be converted into a downstream decision simply by having favorable Tape.

## 20. Routing input model

Define:

    ResearchDecisionRoutingInputs

with fields matching the existing route_playbooks() non-Tape inputs:

    fundamentals_intact: bool = False
    true_catalyst: bool = False
    breakout_confirmed: bool = False
    squeeze_confirmed: bool = False
    stable_regime: bool = False
    overheated_without_upgrade: bool = False
    pair_divergence: bool = False
    structural_repricing: bool = False
    world_confidence: str = "unknown"

theme_key is supplied separately because it is also written into the Decision Object.

Tape state/stage are never supplied separately.

## 21. Exact Tape binding

compile_research_gated_decision accepts one explicit:

    TapeAssessment

It passes:

    tape.state
    tape.stage

directly to route_playbooks().

The caller cannot provide separate tape_state/tape_stage values.

This prevents stale or mismatched routing relative to the stored Tape object.

## 22. Exact theme-key binding

compile_research_gated_decision accepts one:

    theme_key: bool

The exact same boolean is passed to:

    route_playbooks(...)
    compile_decision(...)

The integration layer must not accept two theme-key values.

## 23. World-confidence binding

The routing world confidence comes only from:

    routing_inputs.world_confidence

The exact same string is passed as Decision Object world_confidence.

Do not accept a second independent world_confidence argument.

This prevents routing/decision divergence.

## 24. Existing playbook semantics are authoritative

The integration layer calls route_playbooks() exactly once.

It does not:

- add research readiness points to NoTrade;
- modify raw scores;
- modify normalized scores;
- select another playbook;
- rewrite rationale;
- overwrite action.

## 25. Research admission does not imply an executable action

Examples:

READY research + theme_key False + valid B2 Tape:

    route_playbooks -> WATCH_ONLY

The integration output remains WATCH_ONLY.

READY research + falling_knife Tape:

    route_playbooks -> BLOCKED

The integration output remains BLOCKED.

READY research + clean_retest B3 + Theme key:

    route_playbooks may -> BUILD_ON_RETEST

The integration output preserves that action exactly.

## 26. Decision compiler semantics are authoritative

After ADMITTED research and routing, Increment 12 calls existing:

    compile_decision(...)

exactly once.

The child Decision Object must retain its existing:

- created_at behavior;
- decision_payload_hash behavior;
- Tape representation;
- Playbook representation;
- action;
- optional metadata;
- no-broker-execution meaning.

## 27. Decision theme and ticker are derived

The downstream compile_decision call receives:

    theme = admission.theme_id
    ticker = admission.ticker

The caller cannot pass separate theme/ticker values to the compilation API.

This prevents cross-context leakage after admission.

## 28. Routing result is not accepted from caller

compile_research_gated_decision does not accept a PlaybookRouting object.

It derives the routing result itself from:

    exact TapeAssessment
    exact theme_key
    ResearchDecisionRoutingInputs

This prevents a PlaybookRouting object computed from unrelated Tape or flags from being attached to the Decision Object.

## 29. Compilation record

Define:

    ResearchGatedDecisionCompilation

Required fields:

    admission
    readiness_assessment_hash
    candidate_archive_record_hash
    work_order_hash
    theme_id
    ticker
    tape
    routing
    decision
    compilation_hash

The decision field is the exact dictionary returned by compile_decision().

## 30. Compilation hash

Compute:

    compilation_hash =
        canonical_hash(
            compilation payload excluding compilation_hash
        )

The payload includes the exact child Decision Object.

## 31. Admission is deterministic; compilation is eventful

Increment 12 must explicitly preserve this distinction:

    admission
        = deterministic derived state

    compilation
        = issuance event with created_at

Repeated admission evaluation over identical inputs must have identical hashes.

Repeated decision compilation may differ because existing compile_decision() uses current UTC created_at.

Increment 12 does not change that behavior.

## 32. No fake replay determinism

Do not overwrite or inject created_at after compile_decision() merely to make tests deterministic.

Do not recompute a fake historical Decision Object.

If deterministic replay-time Decision compilation is desired later, it requires a separate explicit contract.

## 33. Existing optional Decision fields

compile_research_gated_decision may forward the existing optional compile_decision metadata:

    dynamic_universe_layer
    company_thesis
    linkage
    radar_run_id
    radar_source_commit
    world_raw
    world_calibrated
    max_permission
    entry_condition
    invalidation
    evidence_refs
    source_timestamps

No new meaning is assigned to them.

## 33A. Target-bearing optional metadata must remain consistent

Optional metadata is forwarded under its existing semantics, but structured metadata that already declares a company target must not contradict the admitted target.

For:

    linkage: LinkageResult | None

if linkage is present:

    normalize(linkage.ticker) == admission.ticker

is required.

Otherwise:

    raise ValueError

This is provenance consistency, not a new research or trading gate.

It prevents a Decision Object authorized for one company from carrying a LinkageResult computed for another company.

## 34. strongest_reason_not_to_trade remains required

The integration compiler preserves the existing required:

    strongest_reason_not_to_trade

Research readiness must not replace this field.

A READY research state can still have a strong reason not to trade.

## 35. No market-freshness gate

Increment 12 does not compare:

    market_asof
    research evidence_as_of
    created_at

to invent a freshness policy.

No age threshold is added.

Freshness policy is deferred until it has an explicit contract.

## 36. No automatic Tape assessment

Increment 12 accepts TapeAssessment.

It does not accept OHLCV and does not call assess_tape_state().

This keeps Tape data preparation/classification outside the integration layer.

## 37. No automatic brokerage execution

No broker API, order submission, position mutation, or portfolio mutation is added.

Decision compilation remains analytical.

## 38. No Decision Ledger write path

Increment 12 does not write files or append to ledger/live.

Persistence remains an explicit later operation using existing ledger infrastructure.

## 39. No scalar cross-layer score

Do not add:

    decision_score
    admission_score
    combined_confidence
    research_x_tape_score

The integration layer composes discrete typed states.

## 40. Tampered readiness

If the supplied readiness object differs from a fresh recomputation over records:

    raise ValueError(
        "research decision readiness does not match supplied records"
    )

Even if its readiness_assessment_hash is internally self-consistent.

The fresh public evaluator is the semantic authority.

## 41. Stale READY example

Suppose readiness was READY when records were:

    D0 -> D1

Then a new competing leaf D2 appears.

If the caller reuses the old READY assessment with:

    records = (D0, D1, D2)

the integration layer recomputes readiness and rejects the stale readiness object.

It must not compile a decision from it.

## 42. Cross-theme leakage example

Readiness is generated from:

    theme_id = DataCenter_Infra

The caller cannot ask Increment 12 to compile:

    theme = Genomics_Bio

because theme is derived, not supplied.

## 43. Cross-ticker leakage example

WorkOrder targets:

    ("VRT",)

The caller requests:

    ticker = "NVDA"

Admission raises ValueError.

READY is not transferable across company targets.

## 44. Theme-only leakage example

A THEME_REASSESSMENT reaches READY.

It cannot authorize a ticker-specific Decision Object.

Admission raises ValueError rather than pretending theme-level coverage proves company-level sufficiency.

## 45. Public API

Export from decision_lab:

    ResearchDecisionAdmission
    ResearchDecisionAdmissionStatus
    ResearchDecisionRoutingInputs
    ResearchGatedDecisionCompilation
    evaluate_research_decision_admission
    compile_research_gated_decision

No existing public export is removed.

## 46. Expected implementation surface

    src/decision_lab/research_decision_integration.py
    src/decision_lab/__init__.py
    tests/test_research_decision_integration.py
    docs/superpowers/specs/2026-09-24-research-decision-integration-design.md
    docs/superpowers/plans/2026-09-24-research-decision-integration.md

Do not modify tape.py, playbooks.py, decision.py, research_decision_readiness.py, or Increment 8-10 modules.

## 47. Core test matrix

Minimum required tests:

1. readiness mismatch against records is rejected;
2. stale READY after a competing leaf appears is rejected;
3. theme reassessment readiness cannot authorize a ticker decision;
4. non-target ticker is rejected;
5. target ticker normalization is deterministic;
6. READY company target -> ADMITTED;
7. NOT_READY -> BLOCKED_NOT_READY;
8. INDETERMINATE -> BLOCKED_INDETERMINATE;
9. admission input permutation is deterministic;
10. admission hash is stable;
11. blocked admission cannot compile;
12. integration derives route from exact Tape state/stage;
13. integration passes one exact theme_key to routing and decision;
14. integration passes one exact world_confidence to routing and decision;
15. READY + theme key off preserves WATCH_ONLY;
16. READY + falling knife preserves BLOCKED;
17. READY + clean retest preserves BUILD_ON_RETEST when router does so;
18. selected playbook/raw/normalized scores are unchanged from direct route_playbooks() with same inputs;
19. child Decision Object Tape equals the supplied TapeAssessment representation;
20. child Decision Object theme/ticker equal bound WorkOrder theme/target;
21. child Decision Object action equals routing.action;
22. strongest_reason_not_to_trade remains caller supplied;
23. compilation hash covers admission, Tape, routing, and child Decision Object;
24. compilation does not write a ledger file;
25. no broker/network/provider API exists;
26. no scalar cross-layer score exists;
27. existing public exports remain;
28. Increment 12 public exports are available.

## 48. TDD requirement

Every implementation task follows real Native RED -> GREEN history.

No fake failures and no unrelated breakage.

## 49. Suggested TDD task split

Task 1:
    deterministic admission + provenance/target binding

Task 2:
    research-gated routing + Decision compilation

Task 3:
    compilation provenance/hash + exact child semantic preservation

Task 4:
    public API + regression boundary

Task 5:
    whole-branch hostile review + exact-final-head qualification

## 50. Review checklist

Before merge explicitly inspect for:

- stale READY acceptance;
- cross-theme readiness leakage;
- cross-ticker readiness leakage;
- theme reassessment authorizing company decision;
- hidden target selection;
- hidden candidate selection;
- routing object accepted from unrelated Tape;
- duplicate theme-key/world-confidence values;
- readiness modifying Playbook scores/action;
- Tape semantics reimplementation;
- market freshness invented from wall clock;
- Decision Object created when research admission is blocked;
- scalar cross-layer scoring;
- Decision Ledger write side effects;
- brokerage side effects;
- changed existing module semantics.

## 51. Completion criterion

Increment 12 is complete when the repository can:

1. deterministically verify that an explicit readiness assessment still matches the supplied research history;
2. bind that readiness to one exact company-deep-dive theme/ticker target;
3. distinguish ADMITTED / BLOCKED_NOT_READY / BLOCKED_INDETERMINATE;
4. refuse downstream compilation unless admitted;
5. derive existing Playbook routing from the exact supplied Tape and one shared Theme-key/world-confidence context;
6. compile the existing Decision Object without rewriting its routing/action semantics;
7. return an auditable integration record binding research provenance to the exact downstream Decision Object;

while adding no broker execution, no freshness heuristic, no scalar combined score, and no hidden branch/target selection.
