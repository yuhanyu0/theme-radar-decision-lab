# Repricing Graph Investment System Design

Date: 2026-09-25
Status: design approved in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: design/repricing-graph-investment-system
Base: c5866ad8f09a472cf631a764f911547c05d337d9

## 1. Purpose

Reorient the project from a research-governance-first system into a usable investment system whose central objective is:

> discover, validate, size, and learn from repeatable equity alpha using information available at the time.

The system must not treat Theme, Scanner, Readiness, Tape, or any single score as alpha by itself.

Its primary economic object is an **expectation gap** between:

1. a model of how reality is changing and how that change transmits into a company's future fundamentals; and
2. a model of what the market currently appears to expect.

The intended investment loop is:

    detect reality change
        -> model causal transmission
        -> infer company fundamental implication
        -> infer market-implied expectation
        -> measure expectation gap
        -> identify a bounded catalyst
        -> estimate repricing state
        -> form a return distribution
        -> size a position
        -> attribute outcome back to model components

The first implementation must be a narrow DataCenter_Infra vertical slice, not a general market ontology.

## 2. Why this design exists

The repository already contains useful infrastructure:

- Theme packages and point-in-time candidate membership;
- market observation adapters;
- world scanning and research allocation;
- research execution and dossiers;
- immutable archive and progression semantics;
- research readiness and research-gated decision integration;
- target-excluded linkage diagnostics;
- Tape path classification;
- playbook routing;
- Decision Objects;
- forward outcome evaluation.

However, those components do not yet define or validate a repeatable alpha mechanism.

The prior generic price-only ALPHA-0 benchmark is retained only as a negative-control benchmark. Its MOM63 / RS20 / ACCEL20 / VOLX strategies are not treated as inherited Theme-system signals and must not be used as evidence that the existing Theme or Market Observation architecture lacks investment value.

This design adds the missing investment core without rewriting the audit infrastructure.

## 3. Core investment hypothesis

The first alpha mechanism is:

### Causal Repricing Lag

A trade candidate exists when all of the following are true:

1. a real-world variable relevant to a Theme changes materially;
2. the change has a documented causal path to a target company's measurable KPI;
3. related peers or layers show evidence that market beliefs are beginning to reprice;
4. the target's own consensus / guidance / price-implied expectation does not yet fully reflect the implied fundamental change;
5. a bounded catalyst can reveal the disputed KPI or implication within the intended holding horizon;
6. target-specific contradictory evidence does not dominate the thesis;
7. expected upside, downside, uncertainty, cost, and correlation justify a position.

The mechanism is not:

    peer prices rise
      -> target did not rise
      -> buy target

A peer/theme move is only a candidate-generation event. It must be connected to an independently evidenced economic transmission path and a measurable expectation gap.

## 4. Core architecture

The system maintains two distinct models for every active investment case.

### 4.1 Reality Model

Represents the system's current estimate of real economic state.

Examples:

- hyperscaler AI capex growth;
- data-center MW additions;
- time-to-power bottlenecks;
- switchgear lead times;
- backlog;
- pricing;
- margins;
- company EPS / FCF implications.

Reality state is not a free-form narrative. Every state estimate must expose:

    variable_id
    as_of
    direction
    central_estimate or range
    unit
    horizon
    confidence
    evidence_refs
    provenance
    revision history

The first vertical slice may use ranges instead of full probability distributions where the underlying data do not justify precise distributions.

### 4.2 Market Belief Model

Represents what the market appears to expect now.

Candidate inputs include:

- company guidance;
- sell-side consensus estimates;
- analyst estimate revisions;
- peer valuation;
- market-implied valuation assumptions;
- observed price reaction;
- option-implied distributions when available;
- public narrative, only when converted into auditable structured claims.

Every market-belief estimate must expose:

    variable_id
    as_of
    central_estimate or range
    inference_method
    confidence
    source_refs
    direct_vs_implied
    staleness

Reality estimates and market-belief estimates are separate typed objects even when numerically identical.

## 5. Repricing Graph

A Repricing Graph is a local causal graph constructed for an active investment case.

It is not a universal company knowledge graph.

### 5.1 Node classes

Minimum node classes:

    WorldState
    ThemeLayerState
    CompanyExposure
    CompanyKPI
    MarketExpectation
    Catalyst
    PriceState

Optional future nodes must not be added until the first vertical slice proves they are necessary.

### 5.2 Edge types

Version 0.1 permits exactly:

    CAUSES
    EXPOSES
    IMPLIES
    REVEALS
    PRICES

Examples:

    hyperscaler_capex
      -CAUSES->
    datacenter_mw_additions

    datacenter_power_demand
      -EXPOSES->
    ETN_electrical_segment

    ETN_orders
      -IMPLIES->
    ETN_FY27_EPS

    earnings_release
      -REVEALS->
    backlog_and_margin

    ETN_share_price
      -PRICES->
    market_implied_FY27_EPS

No edge may exist solely because two series are correlated.

Every edge must carry:

    edge_id
    source_node
    target_node
    edge_type
    direction
    magnitude_or_elasticity_range
    horizon
    confidence
    evidence_refs
    provenance
    status

Permitted status values:

    HYPOTHESIZED
    SUPPORTED
    CONTRADICTED
    RETIRED

## 6. Expectation Gap

The central investment quantity is not a Theme score.

For a company KPI or fundamental variable F:

    fundamental_gap =
        our_expected_F
        - market_expected_F

For a price target or future return distribution:

    expected_alpha =
        E[future_price | Reality Model, Transmission Model]
        - E[future_price | Market Belief Model]

The implementation may initially use scenario ranges rather than a single precise expected value.

The system must preserve:

    our expectation
    market expectation
    gap
    uncertainty on our expectation
    uncertainty on market expectation
    horizon
    catalyst dependency

It is invalid to report a high-confidence expectation gap when either side of the subtraction is unavailable.

## 7. Catalyst model

A catalyst is not a generic label.

It is a bounded information event that can reveal or materially update a disputed graph node.

Required fields:

    catalyst_id
    event_type
    expected_date_or_window
    target_node_ids
    expected_information
    observability
    thesis_relevance
    source_ref
    status

Examples:

- earnings;
- guidance;
- investor day;
- backlog disclosure;
- customer capex update;
- capacity startup;
- contract award;
- regulatory decision.

The system must distinguish:

    gap exists

from:

    gap is likely to be revealed within the investment horizon

A large gap with no plausible reveal path is not automatically a trade.

## 8. Repricing / Tape model

Existing Tape semantics remain unchanged.

Tape is not promoted into an alpha generator.

Its role is:

> describe the current state of price assimilation after a thesis already exists.

For an active Repricing Case, Tape may influence:

- entry timing;
- whether repricing appears to have begun;
- whether a move is extended;
- whether an expected catalyst has already been substantially absorbed;
- invalidation / support mechanics.

Tape must not create a company thesis by itself.

The first version must preserve the existing statement in tape.py that Tape is a router input, not an autonomous trade signal.

## 9. Theme and Market Observation roles

### 9.1 Theme

A Theme becomes a reusable causal scaffold.

Existing ThemeDefinition fields remain valid.

New graph semantics are additive: the Theme may reference an economic-chain template describing the relevant WorldState -> ThemeLayerState paths.

A Theme does not imply a long direction.

### 9.2 Market Observation

Market Observation remains a Theme-level evidence adapter.

Existing measures such as:

- relative strength;
- breadth;
- persistence;
- novelty;

must be interpreted as evidence about **repricing diffusion**, not direct stock-return forecasts.

For example:

    strong breadth + persistence
      -> more of the exposed Theme basket is repricing

It does not mean:

    strong breadth + persistence
      -> buy every member

### 9.3 Scanner

Scanner remains candidate/research-allocation infrastructure.

A high research_priority means:

> investigate whether a repricing mechanism exists.

It does not mean:

> expected return is high.

No implementation may reuse Scanner priority as portfolio weight or expected alpha.

## 10. Linkage role

Existing target-excluded linkage remains diagnostic.

It is used to ask:

- is the target historically connected to the Theme control?
- has that relationship been stable?
- is the target currently decoupling from a repricing Theme basket?
- is the control mechanically circular?

It must not be treated as proof of causal exposure.

A valid investment case requires:

    statistical linkage

plus

    independently evidenced economic exposure

when linkage is used in the thesis.

## 11. Research engine role

Research must be redirected from generic coverage completion toward **decision-value uncertainty reduction**.

Existing WorkOrder / Dossier / Archive / Readiness remain integrity infrastructure.

For investment use, the system must additionally identify:

    key_unknowns

for an active Repricing Case.

Each unknown must expose:

    unknown_id
    affected_graph_nodes
    current_range
    decision_sensitivity
    candidate_research_actions
    estimated_research_cost
    status

The important question is:

> which unresolved variable can materially change expected alpha, downside, or position size?

The system must not spend research budget merely to increase evidence count when the additional evidence cannot change the trade decision.

Version 0.1 does not attempt optimal value-of-information allocation. It only records decision sensitivity explicitly.

## 12. Repricing Case

The principal investment object is:

    RepricingCase

Required fields:

    case_id
    theme_id
    ticker
    as_of
    horizon
    graph_ref
    reality_model_ref
    market_belief_model_ref
    primary_fundamental_variable
    our_expectation
    market_expectation
    expectation_gap
    gap_uncertainty
    catalyst_refs
    current_tape_ref
    upside_scenarios
    downside_scenarios
    thesis
    strongest_counter_thesis
    invalidation_conditions
    key_unknowns
    status
    provenance

Allowed status:

    DISCOVERY
    RESEARCHING
    CANDIDATE
    POSITIONABLE
    INVALIDATED
    CLOSED

POSITIONABLE is not an order instruction.

## 13. Return distribution

The portfolio layer must consume a return distribution or explicit scenarios, not BUY/HOLD/SELL alone.

Minimum representation:

    Bear
    Base
    Bull

Each scenario must have:

    probability_or_weight
    expected_return
    horizon
    condition
    evidence_refs

If probabilities are not calibrated, they must be labeled uncalibrated.

The system may use scenario weights before it has enough history for calibrated probabilities.

Expected alpha must not silently interpret uncalibrated match scores as probabilities.

## 14. Position construction

Position sizing is downstream of the Repricing Case.

Version 0.1 should use a simple, auditable sizing rule rather than a sophisticated optimizer.

Inputs:

    expected alpha / scenario return
    downside
    uncertainty
    liquidity
    target volatility
    portfolio correlation
    theme concentration
    maximum position constraints

The design target is:

    larger position
      when expected payoff is larger
      and uncertainty/downside/correlation are lower

No single Theme, company, or correlated cluster may dominate solely because multiple related cases express the same underlying world shock.

Portfolio-level constraints are mandatory before any live-money use.

## 15. Outcome attribution

Every closed case must be decomposed into model-layer outcomes.

Required attribution axes:

    WORLD_MODEL
    TRANSMISSION
    MARKET_BELIEF
    CATALYST
    TAPE_ENTRY
    POSITION_SIZE

Examples:

    thesis reality correct
    transmission wrong

or:

    fundamental implication correct
    market expectation already priced it

or:

    thesis correct
    catalyst delayed
    entry too early

The system must not reduce all failures to:

    trade lost money

The point of the feedback loop is to learn which component is systematically wrong.

## 16. Existing modules: retain, downgrade, or leave unchanged

### Retain and reuse

    themes.py
    universe.py
    market_observation.py
    scanner.py
    research_budget.py
    research_execution.py
    research_execution_archive.py
    research_progression.py
    research_decision_readiness.py
    research_decision_integration.py
    linkage.py
    tape.py
    outcomes.py
    ledger / archive infrastructure

### Downgrade in authority

    scanner.research_priority
    Theme lifecycle
    Readiness READY
    Tape state
    Playbook score

These remain useful states but are not alpha estimates.

### Preserve unchanged in first implementation

    playbooks.py
    decision.py

The first vertical slice should not rewrite legacy Decision semantics.

A future investment Decision Object may be introduced only after the Repricing Case has been validated.

## 17. New modules anticipated

The design anticipates the following focused modules, but implementation planning may split or rename them if responsibilities remain clear:

    repricing_graph.py
    reality_model.py
    market_belief.py
    repricing_case.py
    catalyst.py
    position_sizing.py
    attribution.py

The first implementation plan must not implement all of them at once.

It must begin with the smallest vertical slice capable of falsifying the first alpha mechanism.

## 18. First vertical slice: DataCenter Causal Repricing Lag

Scope:

    ONE theme: DataCenter_Infra
    ONE world shock family
    ONE sub-layer
    5-10 target companies
    ONE primary KPI per target
    ONE market-expectation variable
    ONE catalyst class
    20d and 60d forward outcomes

Recommended first shock family:

    hyperscaler / data-center capex or power-demand acceleration

Recommended first sub-layer:

    power / electrical infrastructure

Candidate companies may include names already present in the current DataCenter Theme universe, but historical tests must not backfill today's membership before each candidate's documented effective_from unless a separate historical universe is built.

## 19. First falsifiable alpha mechanism

For company i at time t define a candidate event only if:

    A. Theme shock is observed.
    B. Peer/layer repricing is observed using target-excluded controls.
    C. Economic exposure of i is independently supported.
    D. A company KPI implication can be expressed.
    E. A market expectation for that KPI is available.
    F. our implication differs materially from market expectation.
    G. a catalyst exists within horizon.
    H. no dominant company-specific contradiction invalidates transmission.

Primary hypothesis:

> Conditional on A-H, positive expectation gaps are followed by positive target excess returns over 20d/60d more often and with larger average magnitude than matched cases without a positive gap.

This is a mechanism test, not a general signal-library search.

## 20. Required baselines

The first alpha test must compare against:

    SPY
    relevant sector benchmark
    Theme basket
    target-excluded Theme control
    simple price momentum
    peer-minus-target price-gap heuristic

The new mechanism is useful only if it adds information beyond these simpler alternatives.

## 21. Required ablations

At minimum:

    Full mechanism
    - economic exposure validation
    - market expectation gap
    - catalyst requirement
    - Tape context
    - target-excluded control

This identifies where any observed performance actually comes from.

If removing the expectation-gap component leaves performance unchanged, the architecture has failed its central thesis.

## 22. Point-in-time data contract

No serious alpha claim is valid without a point-in-time data contract.

Every observation must expose:

    event_time
    available_at
    source
    revision lineage
    entity
    variable
    value
    unit
    period
    provenance

The system must prohibit:

- revised financial values becoming visible before their publication;
- current Theme membership being backfilled into old dates;
- current consensus being used as historical consensus;
- future catalyst dates being treated as known;
- current company exposure mappings being silently assumed historically;
- delisted/failed companies disappearing from evaluation when a historical universe is used.

Historical data of uncertain availability may be used only for development, not labeled strict PIT validation.

## 23. Market expectation data requirements

This is the largest current data gap.

Priority order:

1. historical company guidance;
2. historical analyst consensus / estimate revisions;
3. price-implied expectations from a frozen valuation inversion;
4. peer / sector expectations as fallback context.

The first alpha mechanism must not substitute current consensus for historical consensus.

If historical consensus cannot be obtained, the first vertical slice must be explicitly scoped to guidance-gap or price-implied-gap research rather than falsely claiming consensus alpha.

## 24. Causal exposure data requirements

Economic exposure must be evidence-backed.

Permitted evidence:

- segment revenue;
- disclosed customer / end-market exposure;
- product / capacity exposure;
- backlog composition;
- management disclosure;
- relevant industry-primary data.

A Candidate.economic_exposure scalar may be used as a summary only if its evidence and effective period are retained.

It must not become an unexplained magic number.

## 25. Catalyst data requirements

Catalyst availability must be point-in-time.

For scheduled events:

    event date
    date event became known
    event type

For unscheduled events:

    available_at
    evidence source

A retrospective event may not be called a prospective catalyst unless the event was knowable before the trade.

## 26. Testing framework

The first implementation must separate:

    mechanism development
    locked evaluation

Because the current DataCenter Theme was created in 2026, a long historical backtest using the current membership would contain hindsight.

Therefore the first implementation should prefer one of:

### Option A — Prospective shadow portfolio
Use the current 2026 Theme from its true effective_from date onward and generate frozen prospective cases.

### Option B — Historical reconstruction
Build a separately documented historical Theme membership/exposure dataset from timestamped evidence before evaluating earlier periods.

Option A is lower-risk and should be the default unless a credible PIT historical dataset is available.

## 27. Evaluation metrics

### Case level

    expected gap
    realized 20d excess return
    realized 60d excess return
    MFE
    MAE
    time to catalyst
    expectation revision after catalyst
    thesis invalidation occurrence

### Cross-sectional / model level

    sign accuracy
    mean / median excess return
    rank correlation where sample size permits
    calibration by gap bucket
    ablation deltas
    cost-adjusted result
    drawdown contribution

### Portfolio level

Only after enough independent cases exist:

    CAGR
    Sharpe / Sortino
    max drawdown
    turnover
    beta
    theme concentration
    correlation
    capacity / liquidity

No portfolio result may be reported from a handful of overlapping cases as if they were independent trades.

## 28. Outcome-learning contract

Outcome attribution must update model diagnostics, not silently mutate historical decisions.

Examples:

    repeated WORLD_MODEL misses
      -> lower confidence in source/variable model

    repeated TRANSMISSION misses
      -> revise edge / exposure assumptions

    repeated MARKET_BELIEF misses
      -> improve consensus / valuation inversion

    repeated CATALYST timing misses
      -> revise horizon / catalyst model

    repeated TAPE_ENTRY misses
      -> revisit execution timing only

Learning must be component-specific.

## 29. What ALPHA-0 becomes

The completed generic ETF ALPHA-0 is retained as:

    GENERIC_PRICE_BASELINE_NEGATIVE_CONTROL

Its results may be used to demonstrate that:

- generic price heuristics were not automatically promoted into the investment system;
- complex architecture must beat simple baselines;
- Tape used as a naive B2/B3/A1 filter did not establish value.

It must not be cited as a test of Theme, Scanner, Market Observation, or Repricing Graph alpha.

## 30. Kill criteria

The first vertical slice must be killed or materially redesigned if any of the following occurs:

1. expectation-gap cases do not outperform matched simpler baselines after realistic costs;
2. the expectation-gap term adds no incremental information in ablation;
3. economic exposure cannot be made point-in-time and evidence-backed;
4. market expectation data cannot be reconstructed without hindsight;
5. target-excluded Theme repricing provides no incremental information beyond target momentum;
6. catalyst requirement does not improve timing or merely selects past winners;
7. returns are concentrated in one company or one overlapping event cluster;
8. performance disappears under modest cost / timing perturbation;
9. the mechanism only works after repeated post-hoc threshold tuning;
10. outcome attribution cannot distinguish model failure from execution noise.

If killed, do not compensate by adding more signals.

## 31. Success criteria for version 0.1

Version 0.1 succeeds when it can produce at least one complete, auditable Repricing Case from real point-in-time inputs with:

- explicit Reality Model;
- evidence-backed company transmission;
- explicit Market Belief Model;
- numerical or interval expectation gap;
- point-in-time catalyst;
- existing Tape context;
- scenario-based return estimate;
- clear invalidation;
- no use of future information;
- frozen 20d/60d evaluation;
- outcome attribution.

This is a system success criterion, not proof of alpha.

Alpha success requires a later locked sample of multiple independent cases.

## 32. Non-goals

Version 0.1 does not attempt:

- a universal knowledge graph;
- a fully automated LLM portfolio manager;
- end-to-end reinforcement learning;
- high-frequency trading;
- options strategy optimization;
- causal identification from price correlation alone;
- full-market historical Theme reconstruction;
- automatic live brokerage execution;
- replacing the existing research integrity stack;
- optimizing dozens of technical indicators.

## 33. Safety and execution boundary

No live trade may be created directly by the new modules.

The first implementation is research / shadow-decision only.

Any future live execution layer requires a separate design with:

- explicit capital limits;
- broker isolation;
- human approval;
- order validation;
- reconciliation;
- kill switch;
- monitoring.

## 34. Design principle

Every new component must answer exactly one of these questions:

    REALITY:
    What is changing in the world?

    TRANSMISSION:
    Why and how does that change affect this company?

    MARKET BELIEF:
    What does the market currently appear to expect?

    CATALYST:
    What can reveal the gap within our horizon?

    REPRICING / EXECUTION:
    How much of the gap is already being absorbed?

    PORTFOLIO:
    Is the payoff worth the downside, uncertainty, correlation, and cost?

If a proposed component answers none of these, it does not belong in the core investment system.

## 35. Architecture invariant

The system's central invariant is:

    Theme != alpha
    Scanner priority != alpha
    Readiness != alpha
    Tape != alpha
    Playbook score != alpha

Alpha exists only when the system can state and test:

    Reality expectation
      !=
    Market-implied expectation

and can explain a plausible causal and temporal path by which that gap may close.

## 36. Transition from design to implementation

The implementation plan must begin with a **single DataCenter vertical slice**, not the full module list.

The first plan should deliver, in order:

1. typed Repricing Case / graph objects;
2. one frozen DataCenter causal template;
3. one target/company transmission representation;
4. one market-expectation input path;
5. one expectation-gap calculation;
6. one catalyst record;
7. one real shadow case;
8. one falsification/evaluation harness.

Portfolio optimization and generalized graph authoring are explicitly deferred until that slice survives its kill criteria.
