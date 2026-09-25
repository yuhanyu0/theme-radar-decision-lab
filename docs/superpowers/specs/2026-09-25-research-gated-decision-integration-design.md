# Increment 12 — Research-Gated Decision Integration Design

Date: 2026-09-25
Status: approved in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: feature/research-gated-decision-integration

## 1. Purpose

Connect the frozen research-readiness layer to the existing Tape / Playbook / Decision pipeline without collapsing their semantics.

Target chain:

    ResearchDossierArchiveRecord[]
        -> Research Decision Readiness
        -> explicit research admission
        -> TapeAssessment
        -> route_playbooks(...)
        -> legacy Decision Object
        -> auditable ResearchGatedDecisionEnvelope

Increment 12 answers:

    may this exact research state authorize compilation
    of a ticker-level Decision Object, and if so,
    what market action did the existing router produce?

It does not answer:

    should an order be sent?
    is the research thesis true?
    is the playbook probability calibrated?
    which research fork should be selected?
    what position size should be used?

## 2. Core separation

The system must preserve three distinct layers:

    research sufficiency
    market execution state
    decision recording

Therefore:

    readiness status
        != Tape state

    Tape state
        != playbook action

    playbook action
        != brokerage execution

    READY
        != BUILD_ON_RETEST
        != AGGRESSIVE_PROBE
        != BUY

## 3. Selected architecture

Add:

    src/decision_lab/decision_integration.py

Keep existing:

    assess_research_decision_readiness(...)
    assess_tape_state(...)
    route_playbooks(...)
    compile_decision(...)

as semantic authorities.

Increment 12 composes them; it does not reimplement them.

## 4. Backward-compatible reproducible Decision Object

Existing compile_decision() uses ambient wall-clock time for created_at.

Add one optional keyword:

    created_at: str | None = None

Behavior:

    created_at is None
        -> preserve current datetime.now(timezone.utc).isoformat() behavior

    created_at is provided
        -> use the exact provided non-empty string

No existing call must change behavior.

The new Increment 12 wrapper always supplies explicit created_at so an integrated Decision Object is reproducible.

## 5. Routing provenance

PlaybookRouting does not store the arguments that produced it.

Increment 12 therefore must not accept an arbitrary precomputed PlaybookRouting as authoritative.

Define:

    DecisionRoutingInputs

containing only route_playbooks inputs that are not already carried by TapeAssessment:

    theme_key
    fundamentals_intact
    true_catalyst
    breakout_confirmed
    squeeze_confirmed
    stable_regime
    overheated_without_upgrade
    pair_divergence
    structural_repricing
    world_confidence

Do not include:

    tape_state
    tape_stage

Those are always taken from the supplied TapeAssessment.

Increment 12 internally calls:

    route_playbooks(
        tape_state=tape.state,
        tape_stage=tape.stage,
        ...
    )

This creates an auditable Tape -> routing relation.

## 6. Research admission status

Define:

    class ResearchDecisionAdmissionStatus(str, Enum):
        RESEARCH_NOT_READY
        RESEARCH_INDETERMINATE
        RESEARCH_SCOPE_MISMATCH
        ADMITTED

These states describe only whether a ticker-level Decision Object may be compiled.

They do not replace PlaybookRouting.action.

## 7. Readiness mapping

Increment 12 internally calls:

    assess_research_decision_readiness(
        records,
        candidate_archive_record_hash,
    )

Mapping:

    NOT_READY
        -> RESEARCH_NOT_READY

    INDETERMINATE
        -> RESEARCH_INDETERMINATE

    READY
        -> continue to research-scope validation

The caller cannot pass a fabricated readiness assessment.

## 8. Ticker-level decisions require company-level research

A legacy Decision Object is ticker-specific.

Therefore research admission for a ticker-level Decision Object requires:

    work_order.research_mode == COMPANY_DEEP_DIVE

A READY theme-reassessment WorkOrder is not sufficient for ticker-level decision compilation.

Result:

    READY theme reassessment
        -> RESEARCH_SCOPE_MISMATCH

This does not mean the theme research is bad.
It means its scope is too broad for the requested ticker-level Decision Object.

## 9. Theme binding

The requested decision theme must exactly equal:

    work_order.theme_id

Mismatch:

    -> RESEARCH_SCOPE_MISMATCH

No fuzzy alias matching.

## 10. Ticker binding

For COMPANY_DEEP_DIVE, requested ticker is normalized to uppercase and must exactly match one frozen WorkOrder target ticker.

Mismatch:

    -> RESEARCH_SCOPE_MISMATCH

No nearest ticker, universe lookup, or fallback.

## 11. Market routing is separate from research admission

Increment 12 may derive the market routing even when research is not admitted.

This is descriptive/counterfactual market state only.

Define:

    market_action = routing.action

always.

Define:

    admitted_action =
        routing.action
        if admission_status == ADMITTED
        else None

Thus:

    research not admitted + B3 Tape
        may still have market_action == BUILD_ON_RETEST

but:

    admitted_action == None
    decision == None

This is intentional.

## 12. Market BLOCKED remains a valid admitted decision

If research is ADMITTED but the existing router returns:

    BLOCKED

Increment 12 still compiles the Decision Object.

Reason:

    market BLOCKED is itself a valid decision outcome.

Do not confuse:

    research blocked
with
    market blocked.

## 13. WATCH_ONLY remains a valid admitted decision

Likewise:

    ADMITTED research
    + routing.action == WATCH_ONLY

produces a Decision Object whose action remains WATCH_ONLY.

Increment 12 does not upgrade it.

## 14. No playbook score reinterpretation

Existing normalized scores remain match scores, not calibrated probabilities.

Increment 12 must preserve:

    routing.probability_is_calibrated

without reinterpretation.

No threshold or winner override is added.

## 15. Decision compile request

Define:

    ResearchGatedDecisionCompileRequest

Required fields:

    decision_id
    created_at
    market_asof
    theme
    ticker
    theme_state
    company_state
    strongest_reason_not_to_trade
    model_version
    config_payload

Optional fields mirror current compile_decision optional inputs:

    dynamic_universe_layer
    company_thesis
    linkage
    radar_run_id
    radar_source_commit
    world_raw
    world_calibrated
    world_confidence
    max_permission
    entry_condition
    invalidation
    evidence_refs
    source_timestamps

The request does not contain Tape or PlaybookRouting.

## 16. Explicit created_at

ResearchGatedDecisionCompileRequest.created_at must be a non-empty string.

Increment 12 does not read the wall clock.

The exact string is passed to compile_decision(created_at=...).

## 17. Integration assessment

Define:

    ResearchDecisionIntegration

Required fields:

    readiness_assessment
    research_mode
    work_order_theme_id
    work_order_target_tickers
    requested_theme
    requested_ticker
    admission_status
    scope_mismatch_reasons
    tape
    tape_hash
    routing_inputs
    routing_inputs_hash
    routing
    routing_hash
    market_action
    admitted_action
    limitations
    integration_hash

## 18. Scope mismatch reasons

For deterministic audit, use fixed reason strings:

    "company-level research is required"
    "decision theme does not match research work order"
    "decision ticker is not a frozen research target"

Reasons are emitted in that fixed order when applicable.

No free-form model reasoning is used.

## 19. Tape identity

Compute:

    tape_hash = canonical_hash(asdict(tape))

No claim is made that TapeAssessment is independently truthful; the hash only identifies the supplied assessment.

## 20. Routing-input identity

Compute:

    routing_inputs_hash = canonical_hash(asdict(routing_inputs))

## 21. Routing identity

Convert routing mappings to ordinary dictionaries and compute a canonical routing payload.

Compute:

    routing_hash = canonical_hash(routing payload)

Do not rely on mapping implementation order.

## 22. Integration identity

Compute:

    integration_hash =
        canonical_hash(
            integration payload excluding integration_hash
        )

The integration payload includes the full readiness assessment, Tape, routing inputs, routing, admission state, and scope reasons.

## 23. Integrated envelope

Define:

    ResearchGatedDecisionEnvelope

Required fields:

    integration
    decision
    envelope_hash

where:

    decision: dict[str, Any] | None

## 24. Compilation rule

If:

    integration.admission_status != ADMITTED

then:

    decision is None

No legacy Decision Object is compiled.

If:

    integration.admission_status == ADMITTED

then call the existing compiler with:

    tape = integration.tape
    routing = integration.routing
    created_at = request.created_at

and all remaining fields from ResearchGatedDecisionCompileRequest.

## 25. Envelope identity

Compute:

    envelope_hash =
        canonical_hash(
            {
                "integration": asdict(integration),
                "decision": decision,
            }
        )

Because admitted compilation uses explicit created_at, the same valid inputs produce the same envelope hash.

## 26. Input-order determinism

For any permutation of the same valid research archive set:

    evaluate_research_decision_integration(...)
    compile_research_gated_decision(...)

must return identical output and hashes.

## 27. Theme/ticker request normalization

Requested ticker:

    strip()
    upper()

Requested theme:

    strip()

Blank theme/ticker raises ValueError.

Do not normalize theme case.

## 28. Decision compile request validation

At minimum reject:

- blank decision_id;
- blank created_at;
- blank market_asof;
- blank theme;
- blank ticker;
- blank theme_state;
- blank company_state;
- blank strongest_reason_not_to_trade;
- blank model_version.

Do not invent defaults for these fields.

## 29. No research branch selection

The caller still provides:

    candidate_archive_record_hash

Increment 12 never selects:

- latest leaf;
- earliest leaf;
- lowest burden;
- READY leaf;
- best Tape branch.

Increment 11 remains responsible for returning INDETERMINATE when appropriate.

## 30. No market freshness heuristic

Increment 12 does not compare market_asof or created_at to wall-clock time.

No:

    datetime.now()
    time.time()

inside decision_integration.py.

The only ambient-time behavior that remains is the legacy default path of compile_decision when callers outside Increment 12 omit created_at.

## 31. No brokerage behavior

No order placement, broker API, position sizing, portfolio mutation, or live trading action is added.

The integrated Decision Object remains a record.

## 32. No writer

Increment 12 does not add a filesystem writer.

Existing write_immutable_json remains available to callers.

Persistence policy is separate from composition semantics.

## 33. Legacy compile_decision compatibility

Existing callers that do not use Increment 12 continue to work.

Increment 12 does not globally forbid direct compile_decision calls.

Therefore the completion claim is:

    an auditable research-gated compilation path now exists

not:

    every possible Decision Object is globally research-gated

## 34. Decision schema

Increment 12 does not modify schemas/decision.schema.json.

The nested legacy Decision Object remains schema-compatible with its existing contract.

The outer ResearchGatedDecisionEnvelope is a typed Python composition object in this increment.

A persistent envelope schema is deferred.

## 35. Public API

Export from decision_lab:

    DecisionRoutingInputs
    ResearchDecisionAdmissionStatus
    ResearchDecisionIntegration
    ResearchGatedDecisionCompileRequest
    ResearchGatedDecisionEnvelope
    evaluate_research_decision_integration
    compile_research_gated_decision

No existing public export is removed.

## 36. Expected implementation surface

    docs/superpowers/specs/2026-09-25-research-gated-decision-integration-design.md
    docs/superpowers/plans/2026-09-25-research-gated-decision-integration.md
    src/decision_lab/decision.py
    src/decision_lab/decision_integration.py
    src/decision_lab/__init__.py
    tests/test_decision_integration.py

No changes are expected in:

    research_execution.py
    research_execution_archive.py
    research_progression.py
    research_decision_readiness.py
    tape.py
    playbooks.py
    ledger.py
    schemas/decision.schema.json

## 37. Core test matrix

Minimum tests:

1. compile_decision explicit created_at is preserved exactly;
2. compile_decision default created_at path remains available;
3. DecisionRoutingInputs has no tape_state/tape_stage field;
4. integration routing equals direct route_playbooks result for supplied Tape;
5. routing hash/input hash are deterministic;
6. research NOT_READY -> RESEARCH_NOT_READY and no admitted action;
7. research INDETERMINATE -> RESEARCH_INDETERMINATE and no admitted action;
8. READY THEME_REASSESSMENT -> RESEARCH_SCOPE_MISMATCH;
9. wrong theme -> RESEARCH_SCOPE_MISMATCH;
10. wrong ticker -> RESEARCH_SCOPE_MISMATCH;
11. READY matching COMPANY_DEEP_DIVE -> ADMITTED;
12. research mismatch reasons have fixed deterministic order;
13. research not admitted may still expose market_action;
14. admitted market BLOCKED compiles Decision Object with BLOCKED unchanged;
15. admitted WATCH_ONLY compiles Decision Object with WATCH_ONLY unchanged;
16. admitted BUILD_ON_RETEST remains BUILD_ON_RETEST;
17. non-admitted envelope has decision=None;
18. admitted envelope embeds exact readiness/integration provenance;
19. same inputs + explicit created_at produce identical envelope/hash;
20. research-record input permutation does not change integration/envelope;
21. blank compile-request identity fields are rejected;
22. no Tape/Playbook semantics are reimplemented;
23. no network/filesystem/broker/wall-clock use in decision_integration.py;
24. Increment 9-11 public APIs remain available;
25. Increment 12 exports are available.

## 38. TDD plan

Every semantic task must preserve Native RED -> GREEN history.

## 39. Review gate

Before merge:

- exact-final-head pytest passes;
- changed Python files pass Ruff;
- exact final changed-file surface is 6 planned files;
- no temporary lint workflow remains;
- hostile review verifies no readiness/action conflation;
- hostile review verifies no branch selection;
- hostile review verifies theme/ticker/work-order scope binding;
- hostile review verifies legacy compile_decision compatibility;
- self-review limitation is disclosed if no independent reviewer exists.

## 40. Completion criterion

Increment 12 is complete when the repository provides one deterministic, auditable path in which:

    validated research history
      -> explicit readiness
      -> company-level target binding
      -> Tape-bound playbook routing
      -> research admission
      -> legacy Decision Object when admitted
      -> immutable envelope identity

while preserving:

    READY != trade permission
    research blocked != market BLOCKED
    market action != brokerage execution
    theme research != ticker research
    Tape != research evidence
    routing score != calibrated probability.
