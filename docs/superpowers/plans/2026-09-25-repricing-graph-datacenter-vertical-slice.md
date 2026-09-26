# DataCenter Repricing Graph Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one shadow-only, point-in-time DataCenter Repricing Case for ETN that connects a documented power/electrical demand shock to a company KPI implication, an explicit market-expectation input, a catalyst, existing Tape context, and frozen 20d/60d outcome evaluation without changing the production decision stack.

**Architecture:** Implement the first Repricing Graph slice under `experiments/repricing_graph_v0_1/` rather than promoting unvalidated objects into `src/decision_lab`. The experiment imports the existing Theme, linkage, Tape, evidence, and outcome machinery but keeps new graph/case semantics isolated until the mechanism survives its kill criteria. The vertical slice is ETN in `DataCenter_Infra/electrical_switchgear`, with one primary fundamental variable and one earnings/guidance catalyst path.

**Tech Stack:** Python 3.11+, dataclasses/enums, PyYAML, pandas/numpy already used by the repository, pytest, existing `decision_lab` modules.

**Spec:** `docs/superpowers/specs/2026-09-25-repricing-graph-investment-system-design.md`

## Global Constraints

- Do not modify existing behavior in `themes.py`, `market_observation.py`, `scanner.py`, `research_budget.py`, `linkage.py`, `tape.py`, `playbooks.py`, `decision.py`, or the Increment 8–12 research stack.
- Do not export new public API from `decision_lab.__init__` in this first slice.
- Do not create live orders, broker calls, or portfolio sizing.
- First target is exactly `ETN`; Theme is exactly `DataCenter_Infra`; layer is exactly `electrical_switchgear`.
- First primary fundamental variable is `ETN_FY2026_ADJUSTED_EPS`; segment demand evidence may include Electrical Americas orders, backlog, and organic growth only as causal/transmission inputs.
- A market expectation must have an explicit method and point-in-time source. It may be `SELL_SIDE_CONSENSUS`, `COMPANY_GUIDANCE`, or `PRICE_IMPLIED`, but company guidance must never be mislabeled as sell-side consensus.
- The catalyst class is the next known ETN earnings/guidance update after the case `as_of`; its event date/window must include when that date became knowable.
- Existing Market Observation metrics remain Theme repricing evidence, not expected-alpha scores.
- Existing linkage remains diagnostic and may not establish causal exposure by itself.
- Existing Tape remains an assimilation/entry-context input and may not create the thesis.
- Every case input must carry `event_time`, `available_at`, source/provenance, and revision lineage where applicable.
- Current 2026 Theme membership must not be backfilled to dates before its documented effective period.
- First evaluation is a prospective/current shadow case. Historical reconstruction is deferred.
- 20d/60d outcomes are frozen evaluation targets; future outcomes are appended later and never used to mutate the original case.
- ALPHA-0 remains a generic price negative control, not evidence for or against this mechanism.
- If the expectation-gap component adds no distinct information to the case or cannot be constructed without hindsight, trigger the kill criterion rather than adding more signals.

## Review Focus

1. **Market expectation provenance:** reject a `MarketExpectation` whose method says `SELL_SIDE_CONSENSUS` but whose source is management guidance, and reject values whose `available_at` exceeds the case `as_of`.
2. **Causal edge provenance:** reject `EXPOSES` / `IMPLIES` edges with no evidence refs or with a purely statistical linkage ref as their only support.
3. **Theme membership timing:** reject a shadow case whose ETN/Theme membership is not effective at the case date.
4. **Catalyst hindsight:** reject a catalyst whose scheduled date was not known by the case `as_of`, even if the event later occurred as expected.
5. **Expectation-gap false precision:** reject a point estimate labeled calibrated when either the Reality estimate or Market expectation is an interval / uncalibrated inference.

---

### Task 1: Experimental Repricing Graph types and invariants

**Files:**
- Create: `experiments/repricing_graph_v0_1/model.py`
- Create: `experiments/repricing_graph_v0_1/test_model.py`

**Interfaces:**
- Consumes: no new project interfaces; may use `decision_lab.ledger.canonical_hash`.
- Produces:
  - `NodeType`
  - `EdgeType`
  - `EdgeStatus`
  - `EstimateKind` with exactly `POINT` and `INTERVAL`
  - `MarketExpectationMethod` with exactly `SELL_SIDE_CONSENSUS`, `COMPANY_GUIDANCE`, and `PRICE_IMPLIED`
  - `GraphNode`
  - `GraphEdge`
  - `RealityEstimate`
  - `MarketExpectation`
  - `CatalystRecord`
  - `ScenarioReturn`
  - `KeyUnknown`
  - `RepricingGraph`
  - `RepricingCase`
  - `validate_repricing_graph(graph: RepricingGraph) -> None`
  - `validate_repricing_case(case: RepricingCase) -> None`

- [ ] **Step 1: Write failing tests for the frozen type contract**

Tests must assert:
- allowed node types are exactly `WORLD_STATE`, `THEME_LAYER_STATE`, `COMPANY_EXPOSURE`, `COMPANY_KPI`, `MARKET_EXPECTATION`, `CATALYST`, `PRICE_STATE`;
- allowed edges are exactly `CAUSES`, `EXPOSES`, `IMPLIES`, `REVEALS`, `PRICES`;
- graph edges reject missing node ids;
- graph edges reject empty evidence/provenance;
- statistical linkage alone cannot validate an `EXPOSES` edge;
- estimates reject `available_at > as_of`;
- generic RepricingCase validation remains ticker-agnostic; ETN-only scope is enforced later by the vertical-slice profile validator;
- scenario weights must be non-negative and cannot be called calibrated probabilities unless `probability_is_calibrated=True`.

- [ ] **Step 2: Run Task 1 tests and retain RED evidence**

Run:

`pytest -q experiments/repricing_graph_v0_1/test_model.py`

Expected: import/module failure before implementation.

- [ ] **Step 3: Implement the minimal frozen dataclasses/enums/validators**

Implement only the interfaces listed above in `model.py`. Use immutable dataclasses. Do not add graph traversal, scoring, LLM calls, persistence, or generalized Theme authoring.

- [ ] **Step 4: Run Task 1 tests to GREEN**

Run:

`pytest -q experiments/repricing_graph_v0_1/test_model.py`

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit**

`git add experiments/repricing_graph_v0_1/model.py experiments/repricing_graph_v0_1/test_model.py && git commit -m "feat: add experimental repricing graph model"`

---

### Task 2: Expectation-gap and scenario calculation

**Files:**
- Create: `experiments/repricing_graph_v0_1/gap.py`
- Create: `experiments/repricing_graph_v0_1/test_gap.py`

**Interfaces:**
- Consumes:
  - `RealityEstimate`
  - `MarketExpectation`
  - `ScenarioReturn`
- Produces:
  - `ExpectationGap`
  - `ScenarioSummary`
  - `calculate_expectation_gap(ours: RealityEstimate, market: MarketExpectation) -> ExpectationGap`
  - `summarize_scenarios(scenarios: tuple[ScenarioReturn, ...]) -> ScenarioSummary`

- [ ] **Step 1: Write failing tests for interval-safe gap semantics**

Tests must assert:
- same variable/unit/period/horizon are required;
- a point-vs-point estimate produces a numerical gap;
- interval-vs-point and interval-vs-interval preserve an interval gap;
- an uncalibrated input cannot yield a calibrated gap;
- missing market expectation fails rather than substituting price momentum;
- scenario summary exposes weighted expected return only when weights are explicitly supplied;
- no playbook score or scanner priority can be passed as a probability.

- [ ] **Step 2: Run Task 2 tests to verify RED**

Run:

`pytest -q experiments/repricing_graph_v0_1/test_gap.py`

Expected: missing implementation.

- [ ] **Step 3: Implement minimal interval arithmetic and scenario summary**

Use transparent arithmetic only. Do not fit models or infer probabilities.

- [ ] **Step 4: Run Task 1–2 tests to GREEN**

Run:

`pytest -q experiments/repricing_graph_v0_1/test_model.py experiments/repricing_graph_v0_1/test_gap.py`

- [ ] **Step 5: Commit**

`git add experiments/repricing_graph_v0_1/gap.py experiments/repricing_graph_v0_1/test_gap.py && git commit -m "feat: calculate repricing expectation gaps"`

---

### Task 3: Freeze the DataCenter electrical causal template

**Files:**
- Create: `experiments/repricing_graph_v0_1/datacenter_etn_template.yaml`
- Create: `experiments/repricing_graph_v0_1/template.py`
- Create: `experiments/repricing_graph_v0_1/test_template.py`

**Interfaces:**
- Consumes:
  - existing `config/themes/datacenter_infra.yaml`
  - existing `config/datacenter_seed.example.yaml`
- Produces:
  - `load_etn_template(path: str | Path) -> RepricingGraph`
  - one frozen graph template with target `ETN`

The template must contain this minimum path:

    hyperscaler_ai_datacenter_capex
      -CAUSES->
    datacenter_power_demand
      -CAUSES->
    electrical_distribution_demand
      -EXPOSES->
    ETN_electrical_americas
      -IMPLIES->
    ETN_FY2026_ADJUSTED_EPS

It must also contain:

    ETN_next_earnings
      -REVEALS->
    ETN_FY2026_ADJUSTED_EPS

and a market expectation node reached through `PRICES`.

- [ ] **Step 1: Write failing template tests**

Tests must assert:
- Theme id and target are exact;
- ETN maps to `electrical_switchgear`;
- every edge has at least one non-linkage provenance ref;
- no node/edge uses a future `available_at`;
- no unsupported edge type is present;
- every graph path from world shock to EPS contains an evidence-backed company exposure step;
- the template does not contain BUY/SELL, position size, or playbook labels.

Review-focus test: mutate ETN membership date so it is ineffective at case date and assert validation fails.

- [ ] **Step 2: Run Task 3 tests to RED**

Run:

`pytest -q experiments/repricing_graph_v0_1/test_template.py`

- [ ] **Step 3: Implement loader and frozen YAML template**

Keep numeric edge magnitudes empty/ranged until supplied by evidence in the shadow case; do not encode guessed elasticities into the template.

- [ ] **Step 4: Run Task 1–3 tests to GREEN**

Run:

`pytest -q experiments/repricing_graph_v0_1/test_model.py experiments/repricing_graph_v0_1/test_gap.py experiments/repricing_graph_v0_1/test_template.py`

- [ ] **Step 5: Commit**

`git add experiments/repricing_graph_v0_1/datacenter_etn_template.yaml experiments/repricing_graph_v0_1/template.py experiments/repricing_graph_v0_1/test_template.py && git commit -m "feat: freeze ETN datacenter repricing template"`

---

### Task 4: Point-in-time ETN shadow-case input contract

**Files:**
- Create: `experiments/repricing_graph_v0_1/case_io.py`
- Create: `experiments/repricing_graph_v0_1/test_case_io.py`
- Create: `experiments/repricing_graph_v0_1/cases/ETN_2026Q2_shadow.yaml`
- Create: `experiments/repricing_graph_v0_1/cases/ETN_2026Q2_sources.md`

**Interfaces:**
- Consumes:
  - frozen ETN graph template;
  - point-in-time evidence manually curated for the one shadow case;
  - existing `Candidate` effective window semantics.
- Produces:
  - `load_shadow_case(path: str | Path) -> RepricingCase`
  - `validate_point_in_time_case(case: RepricingCase) -> None`
  - `validate_etn_vertical_slice_case(case: RepricingCase, package: ThemePackage) -> None`

The source file must record every input as:

    source_id
    url
    event_time
    available_at
    variable_id
    value/range
    unit
    period
    revision_lineage
    direct_or_inferred
    notes

The initial shadow case uses ETN information available at its chosen `as_of`. Company-primary evidence may include current 2026 Electrical Americas order/backlog/organic-growth disclosures and adjusted EPS guidance. The case file must not hard-code future 20d/60d outcomes.

The Market expectation input must be one of:

1. a timestamped sell-side consensus value;
2. a separately documented price-implied expectation with frozen valuation assumptions;
3. company guidance explicitly labeled `COMPANY_GUIDANCE` as a weaker baseline expectation, never labeled consensus.

- [ ] **Step 1: Write failing PIT-contract tests**

Tests must reject:
- a vertical-slice case whose ticker is not exactly `ETN`;
- a vertical-slice case whose theme/layer is not `DataCenter_Infra/electrical_switchgear`;
- evidence available after case `as_of`;
- missing source/provenance;
- current consensus with no historical availability timestamp;
- management guidance labeled as `SELL_SIDE_CONSENSUS`;
- catalyst date known only after `as_of`;
- ETN membership before the Theme effective date;
- future outcome values embedded in the case input;
- price-implied expectation with unrecorded valuation assumptions.

- [ ] **Step 2: Run Task 4 tests to RED**

Run:

`pytest -q experiments/repricing_graph_v0_1/test_case_io.py`

- [ ] **Step 3: Curate and freeze one real ETN shadow-case input**

Use primary/company sources where possible. Record source URLs and availability timestamps. Do not estimate an expectation gap until both sides of the gap are present.

- [ ] **Step 4: Implement the loader/validator and make the case load successfully**

The loader performs validation only; it must not fetch the web at runtime. Generic `validate_repricing_case` remains reusable; ETN/theme/layer restrictions live only in `validate_etn_vertical_slice_case`.

- [ ] **Step 5: Run Task 1–4 tests to GREEN**

Run all tests under:

`pytest -q experiments/repricing_graph_v0_1/test_*.py`

- [ ] **Step 6: Commit**

`git add experiments/repricing_graph_v0_1/case_io.py experiments/repricing_graph_v0_1/test_case_io.py experiments/repricing_graph_v0_1/cases && git commit -m "feat: freeze point-in-time ETN shadow case"`

---

### Task 5: Existing Theme, linkage, and Tape adapters for the shadow case

**Files:**
- Create: `experiments/repricing_graph_v0_1/context.py`
- Create: `experiments/repricing_graph_v0_1/test_context.py`

**Interfaces:**
- Consumes:
  - existing `ThemePackage`;
  - existing Market Observation output if available at the case date;
  - existing `leave_one_out_control` and `rolling_linkage`;
  - existing `assess_tape_state`.
- Produces:
  - `RepricingContext`
  - `build_repricing_context(...) -> RepricingContext`

Required fields in `RepricingContext`:

    theme_market_observation_ref
    target_excluded_linkage
    tape_assessment
    context_as_of
    warnings

- [ ] **Step 1: Write failing context tests**

Tests must assert:
- target-excluded control mechanically excludes ETN;
- linkage is stored as diagnostic only;
- Tape output is included unchanged and never converted into expected alpha;
- missing Market Observation produces a warning rather than a fabricated score;
- context rejects market data available after `as_of`.

Review-focus test: provide a perfect statistical linkage with no economic-exposure evidence and assert that the case remains non-positionable / incomplete rather than creating an `EXPOSES` edge.

- [ ] **Step 2: Run Task 5 tests to RED**

Run:

`pytest -q experiments/repricing_graph_v0_1/test_context.py`

- [ ] **Step 3: Implement the adapter**

Do not reimplement existing linkage or Tape logic.

- [ ] **Step 4: Run all vertical-slice tests to GREEN**

Run:

`pytest -q experiments/repricing_graph_v0_1/test_*.py`

- [ ] **Step 5: Commit**

`git add experiments/repricing_graph_v0_1/context.py experiments/repricing_graph_v0_1/test_context.py && git commit -m "feat: bind existing context to ETN repricing case"`

---

### Task 6: Shadow-case compiler and frozen decision record

**Files:**
- Create: `experiments/repricing_graph_v0_1/shadow_case.py`
- Create: `experiments/repricing_graph_v0_1/test_shadow_case.py`

**Interfaces:**
- Consumes:
  - loaded ETN `RepricingCase`;
  - `ExpectationGap`;
  - `RepricingContext`.
- Produces:
  - `ShadowRepricingDecision`
  - `compile_shadow_repricing_decision(...) -> ShadowRepricingDecision`

The shadow decision must contain:

    case_hash
    as_of
    ticker
    theme_id
    expectation_gap
    catalyst
    tape_context
    scenarios
    strongest_counter_thesis
    invalidation_conditions
    key_unknowns
    status
    warnings

Allowed status:

    RESEARCHING
    CANDIDATE
    INVALIDATED

The first slice must not emit `POSITIONABLE`, BUY, SELL, or position size.

- [ ] **Step 1: Write failing compilation tests**

Tests must assert:
- no gap -> `RESEARCHING`;
- missing causal exposure evidence -> `RESEARCHING`;
- dominant contradiction -> `INVALIDATED`;
- complete auditable gap + catalyst -> `CANDIDATE`;
- Tape cannot promote an otherwise incomplete case;
- changing only future-outcome fields cannot change the frozen decision because future outcomes are not input fields;
- identical frozen inputs yield identical `case_hash`.

- [ ] **Step 2: Run Task 6 tests to RED**

Run:

`pytest -q experiments/repricing_graph_v0_1/test_shadow_case.py`

- [ ] **Step 3: Implement deterministic shadow compilation**

Use canonical hashing; no wall-clock semantic state in the case hash.

- [ ] **Step 4: Run all vertical-slice tests to GREEN**

- [ ] **Step 5: Commit**

`git add experiments/repricing_graph_v0_1/shadow_case.py experiments/repricing_graph_v0_1/test_shadow_case.py && git commit -m "feat: compile ETN shadow repricing decision"`

---

### Task 7: Falsification and ablation harness

**Files:**
- Create: `experiments/repricing_graph_v0_1/evaluate.py`
- Create: `experiments/repricing_graph_v0_1/test_evaluate.py`
- Create: `experiments/repricing_graph_v0_1/README.md`

**Interfaces:**
- Consumes:
  - frozen `ShadowRepricingDecision`;
  - later immutable close/benchmark/Theme-control series;
  - existing `evaluate_forward_outcomes`.
- Produces:
  - `ShadowOutcomeRecord`
  - `evaluate_shadow_case(...) -> ShadowOutcomeRecord`
  - `run_ablation(case, ablation: Ablation) -> AblationRecord`

Required ablations:

    FULL
    NO_ECONOMIC_EXPOSURE_VALIDATION
    NO_MARKET_EXPECTATION_GAP
    NO_CATALYST_REQUIREMENT
    NO_TAPE_CONTEXT
    NO_TARGET_EXCLUDED_CONTROL

- [ ] **Step 1: Write failing outcome/ablation tests**

Tests must assert:
- 20d/60d outcomes cannot be evaluated before enough future sessions exist;
- evaluation never mutates the frozen case;
- FULL and each ablation retain their exact provenance;
- `NO_MARKET_EXPECTATION_GAP` cannot still claim an expectation-gap mechanism;
- forward return is reported against SPY, relevant sector benchmark, Theme basket/control when supplied;
- MFE/MAE are preserved;
- no p-value or alpha claim is created from one case;
- a failed central ablation is represented as a kill signal, not auto-repaired by another feature.

- [ ] **Step 2: Run Task 7 tests to RED**

Run:

`pytest -q experiments/repricing_graph_v0_1/test_evaluate.py`

- [ ] **Step 3: Implement evaluation and ablation records**

Reuse `decision_lab.outcomes.evaluate_forward_outcomes`; do not duplicate it.

- [ ] **Step 4: Run the entire original repository test suite plus vertical-slice tests**

Run:

`pytest -q`

and:

`pytest -q experiments/repricing_graph_v0_1/test_*.py`

Expected: all original tests remain green; all vertical-slice tests green.

- [ ] **Step 5: Write README scope/kill rules**

README must state:
- shadow-only;
- ETN/DataCenter only;
- no live capital;
- no historical alpha claim from a single current case;
- how and when 20d/60d outcomes are appended;
- which kill criteria terminate expansion.

- [ ] **Step 6: Commit**

`git add experiments/repricing_graph_v0_1/evaluate.py experiments/repricing_graph_v0_1/test_evaluate.py experiments/repricing_graph_v0_1/README.md && git commit -m "feat: evaluate repricing shadow cases"`

---

### Task 8: Whole-slice qualification

**Files:**
- Modify only if a reproducing defect is found in `experiments/repricing_graph_v0_1/`.
- Do not modify existing `src/decision_lab` behavior to make the experiment pass.

**Interfaces:**
- Consumes the complete experimental slice.
- Produces qualification evidence only.

- [ ] **Step 1: Review the whole diff against the spec**

Explicitly inspect for:
- Theme/Scanner/Tape scores leaking into expected alpha;
- target-excluded linkage being treated as causal proof;
- market expectation mislabeled or future-dated;
- hidden hindsight in Theme membership/catalyst/outcomes;
- guessed edge elasticities without evidence;
- position sizing/live trade behavior;
- future outcome leakage into the frozen case;
- post-hoc threshold tuning;
- production API changes outside the experiment.

- [ ] **Step 2: If a defect is found, add a reproducing RED test before fixing it**

Keep real RED -> GREEN history for any semantic repair.

- [ ] **Step 3: Run final exact-head qualification**

Run:

`pytest -q`

Run changed-files Ruff on:

`experiments/repricing_graph_v0_1/*.py`

Verify the production tree relative to base has no changes outside:

    experiments/repricing_graph_v0_1/
    docs/superpowers/specs/2026-09-25-repricing-graph-investment-system-design.md
    docs/superpowers/plans/2026-09-25-repricing-graph-datacenter-vertical-slice.md

- [ ] **Step 4: Record the result without overclaiming**

Successful completion means:

> one auditable ETN shadow Repricing Case exists and can later be evaluated without hindsight.

It does **not** mean:

> the mechanism has alpha.

- [ ] **Step 5: Do not merge into `main` merely because the engineering slice passes**

The experimental branch should remain separate until:
- the one shadow case is frozen;
- enough forward sessions accrue for its outcome;
- the data contract has survived review;
- a later cohort/evaluation plan is approved.

## Deferred until after the first shadow case

The following are explicitly outside this plan:

- 5–10 company cohort;
- portfolio sizing;
- live brokerage;
- generalized graph authoring UI;
- automated LLM graph construction;
- historical Theme reconstruction;
- full historical analyst-consensus database;
- generalized catalyst engine;
- generalized attribution learner;
- public `decision_lab` API promotion;
- portfolio optimization.

## Plan completion criterion

This plan is complete when a developer can create and freeze one ETN/DataCenter Repricing Case using only information available at the declared `as_of`, explain the Reality -> Transmission -> KPI -> Market Expectation -> Gap -> Catalyst chain, attach existing Theme/linkage/Tape context without elevating those diagnostics into alpha, and later append 20d/60d outcomes without changing the original case.
