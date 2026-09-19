# Increment 3 — World Scanner & Research Budget Funnel Design

Date: 2026-09-19
Status: approved in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: feature/world-scanner-research-budget

## 1. Purpose

Add the first market-wide research-allocation layer above the existing generic theme engine.

The system already supports versioned theme definitions and lifecycle states, generic theme packages, effective-dated universes, industry-aware evidence adapters, hierarchical target-excluded linkage, Tape state, A-H routing, fail-closed Theme-key calibration, and immutable decision/outcome infrastructure.

The missing layer is deciding, cheaply and reproducibly, which themes deserve expensive research during each cycle.

Target flow:

    cheap multi-source theme observations
      -> World Scanner
      -> lifecycle recommendation + priority diagnostics
      -> Research Budget Allocator
      -> SCAN_ONLY / THEME_RESEARCH / FULL_DECISION_RESEARCH
      -> existing downstream engine

The scanner allocates research attention. It does not create trade permission.

## 2. Core invariant

Preserve this separation:

    Discovery evidence
      != Theme Registry truth
      != company evidence
      != Tape
      != ThemeKey permission
      != action

A strong Radar observation alone may increase discovery priority, but it can never directly create validated membership, mutate ThemeRegistry, create FULL_DECISION_RESEARCH, satisfy ThemeKey, or create an actionable decision.

## 3. Non-goals

Increment 3 will not:

- run expensive company research across the entire listed market;
- automatically cluster tickers into new themes;
- build a news/NLP ingestion pipeline;
- scrape SEC/IR for every candidate;
- invent permanent theme taxonomies;
- schedule recurring live GitHub Actions research jobs;
- enable live/private Decision Ledger writes in this public repository;
- calibrate economically optimal scanner weights;
- calibrate Genomics ThemeKey thresholds;
- modify Tape states or A-H routing semantics;
- perform portfolio sizing or brokerage execution.

## 4. Considered architectures

### Approach A — Theme-first Scanner + Budget Allocator

Inputs are cheap theme-level observations from model and independent sources. The scanner summarizes discovery, structural maturity, persistence, breadth, relative strength, volatility, novelty, and evidence quality. The allocator chooses which existing themes receive deeper research.

Advantages: fits the current ThemeRegistry/ThemePackage architecture, bounds research cost, preserves model-vs-independent evidence separation, is deterministic and auditable, and avoids requiring a solved clustering problem.

### Approach B — Ticker-first clustering

Scan thousands of securities, cluster co-movement/event/economic features, then infer themes.

This may later improve discovery, but it introduces an unstable ontology/clustering problem and couples discovery, taxonomy, membership, and allocation in one step.

### Approach C — Radar-first routing

Rank themes directly from theme-radar-log and allocate research primarily from model output.

This is simple but makes model output the de facto source of truth and reintroduces circular proof.

### Selected approach

Use Approach A.

Ticker-first discovery may later become another source of ThemeScanObservation, but it is not required for Increment 3.

## 5. New data model

### 5.1 ThemeScanObservation

A cheap, timestamped theme-level evidence item.

Fields:

    theme_id
    as_of
    source_type
    source_ref
    discovery_signal
    structure_signal
    persistence_signal
    breadth_signal
    relative_strength_signal
    volatility_signal
    novelty_signal
    support_direction
    evidence_refs
    is_independent
    observed_or_inferred
    notes

Signal fields are optional floats in [0, 1].

support_direction is one of supporting, neutral, or contradicting.

is_independent is true only when the evidence is not derived from the same Radar/model output being evaluated.

Radar/Navigator observations use source_type = radar_model_output and is_independent = false.

Independent observations may include broad market/sector/theme return and breadth features, volume/dispersion features, official industry statistics, primary event counts, or other non-Radar public data.

### 5.2 ThemeScanResult

One deterministic result per theme/as-of cycle.

Fields:

    theme_id
    as_of
    discovery_score
    structural_score
    persistence_score
    breadth_score
    relative_strength_score
    novelty_score
    evidence_confidence
    independent_support_count
    independent_contradiction_count
    lifecycle_recommendation
    research_priority
    forced_review
    forced_review_severity
    forced_review_reasons
    reasons
    evidence_refs
    config_hash
    registry_version
    prior_result_refs

Scores are diagnostics, not probabilities.

### 5.3 ResearchTier

Three tiers:

    SCAN_ONLY
    THEME_RESEARCH
    FULL_DECISION_RESEARCH

SCAN_ONLY permits cheap observation refresh, scan diagnostics, prior-result comparison, and lifecycle recommendations. It does not trigger expensive company evidence, linkage, Tape, or router work.

THEME_RESEARCH permits value-chain refresh, universe refresh, primary-source evidence gathering for promoted candidates, and contradiction/missingness investigation. It does not imply ThemeKey permission.

FULL_DECISION_RESEARCH permits company evidence normalization, hierarchical controls/linkage, Tape refresh, A-H routing, and decision review under existing dual-key/fail-closed rules.

An uncalibrated theme may enter FULL_DECISION_RESEARCH for research/watch purposes while ThemeKey remains false.

### 5.4 ResearchAllocation

Fields:

    theme_id
    as_of
    tier
    priority
    forced_review
    allocation_reasons
    source_scan_result_hash

This is a research-routing artifact, not a Decision Object.

## 6. Scanner input contract

Public interface:

    rank_themes(
        observations,
        registry_state,
        prior_results,
        config,
        cycle_as_of,
    ) -> list[ThemeScanResult]

### 6.1 Observations

Every observation used for a cycle must satisfy observation.as_of <= cycle_as_of.

Future-dated observations are rejected.

### 6.2 Registry state

The scanner reads the currently effective ThemeDefinition.

It may emit lifecycle_recommendation, but it does not mutate ThemeRegistry. Registry mutation remains a separate explicit operation so scan inference is never confused with registry truth.

### 6.3 Prior results

Only scan results with prior.as_of < cycle_as_of may contribute to persistence, novelty comparison, or repeated-no-change decay.

A prior result with as_of >= cycle_as_of is rejected from historical-feature computation.

## 7. Score construction

All supplied component signals must already be normalized to [0,1].

### 7.1 Separate model from independent evidence

Compute distinct summaries for:

    model_support
    independent_support
    independent_contradiction

Radar/model observations may influence discovery and structural diagnostics. They may not satisfy independent corroboration.

### 7.2 Component aggregation

For each component, aggregate only available values using source-class weights:

    Component_j = sum(w_k * x_jk) / sum(w_k)

Missing components remain None. They are never imputed as zero or one.

### 7.3 Evidence confidence

Evidence confidence rises with multiple independent evidence classes, recent observations, and agreement. It falls with stale observations, direct independent contradiction, model-only coverage, or repeated same-source evidence.

It is a diagnostic score, not a probability.

### 7.4 Research priority

Use a configurable deterministic score:

    Priority_j =
        w_D * discovery
      + w_S * structural
      + w_P * persistence
      + w_B * breadth
      + w_R * relative_strength
      + w_N * novelty
      + w_C * evidence_confidence
      - w_X * contradiction_or_staleness_penalty
      - w_Q * repeated_no_change_penalty

Weights are configuration values, not economic truths.

Version 0.1 may ship public-safe deterministic defaults only to test ranking behavior. The config must label them uncalibrated. They are never ThemeKey thresholds or probabilities.

## 8. Independent corroboration rule

A theme cannot enter ordinary THEME_RESEARCH or FULL_DECISION_RESEARCH solely from model output.

Ordinary promotion requires:

    independent_support_count >= minimum_independent_sources

and no unresolved hard contradiction.

Version 0.1 default:

    minimum_independent_sources = 1

This is a research-routing safety requirement, not a statistical validation claim.

A theme with strong Radar evidence but zero independent support remains SCAN_ONLY.

## 9. Lifecycle recommendations

The scanner may recommend:

    discovery
    forming
    strengthening
    mature
    weakening
    dormant
    retired
    no_change

It never applies these states directly.

Version 0.1 is conservative:

- repeated independent strengthening evidence may recommend strengthening;
- fading persistence/breadth may recommend weakening;
- prolonged absence of support may recommend dormant;
- direct contradiction should usually trigger review rather than immediate retirement;
- split/merge recommendations are deferred.

## 10. Research Budget Allocator

Public interface:

    ResearchBudgetAllocator.allocate(
        scan_results,
        registry_state,
        config,
        cycle_as_of,
    ) -> list[ResearchAllocation]

### 10.1 Capacity controls

Initial configurable caps:

    theme_research_slots = 8
    full_decision_slots = 3

These are resource limits, not empirical market truths.

### 10.2 Ordinary tier eligibility

Every theme starts SCAN_ONLY.

THEME_RESEARCH eligibility requires:

- current effective lifecycle state = strengthening;
- independent corroboration satisfied;
- evidence confidence above configured minimum;
- remaining theme-research capacity.

FULL_DECISION_RESEARCH eligibility requires:

- THEME_RESEARCH eligibility;
- priority and novelty above configured full-research gates;
- remaining full-decision capacity.

ThemeCalibrationState does not control research allocation. Therefore Genomics_Bio may receive FULL_DECISION_RESEARCH while ThemeKey remains false because it is uncalibrated.

## 11. Forced review

Some events must preempt ordinary top-N ranking.

forced_review = true when at least one configured condition is met:

- material contradiction against the prior thesis;
- lifecycle deterioration crossing a configured severity threshold;
- watched expression has a material Tape-state transition;
- explicit invalidation evidence appears;
- major divergence between model and independent evidence;
- source-integrity/staleness failure makes a prior decision basis unreliable.

Forced review:

- reserves a FULL_DECISION_RESEARCH slot;
- may displace the lowest-priority ordinary allocation;
- does not imply positive opportunity;
- does not change ThemeKey;
- records exact reasons and severity.

If forced-review demand exceeds capacity, sort by severity and then deterministic tie-breakers.

## 12. Repeated-no-change decay

Do not repeatedly spend expensive budget on a theme that remains unchanged.

If a theme receives expensive research for consecutive prior cycles while novelty_score < novelty_floor, apply a configurable penalty to ordinary ranking.

This penalty cannot suppress forced review, a new independent contradiction, a lifecycle transition, or a material Tape transition.

History must be strictly prior-dated.

## 13. Determinism and tie-breaking

Given identical observations, registry state, prior results, config, and cycle_as_of, return identical ordered outputs.

Tie-break order:

1. forced review before ordinary allocation;
2. higher forced-review severity;
3. higher research priority;
4. higher evidence confidence;
5. lexical theme_id.

No random tie-breaking.

## 14. Missingness and fail-closed behavior

Examples:

- model-only theme -> SCAN_ONLY;
- missing independent corroboration -> no ordinary promotion;
- stale observations -> confidence/priority penalty;
- future-dated observation -> reject;
- missing signal -> None, never fabricated;
- no prior result -> no historical persistence/decay inference;
- contradictory independent sources -> preserve contradiction and lower confidence;
- unknown theme -> may appear as a discovery candidate, but cannot be sent into package-dependent downstream research until a ThemeDefinition/package exists;
- uncalibrated ThemeKey -> research may continue, permission stays closed.

## 15. Provenance

Each ThemeScanResult preserves:

- evidence refs used;
- cycle as-of;
- scanner config version/hash;
- prior-result refs;
- current ThemeDefinition version;
- model-vs-independent source counts.

Each ResearchAllocation binds to the exact scan-result hash that produced it.

No allocation may depend on evidence absent from result provenance.

## 16. Public-repository safety

Allowed in this public repo:

- public-safe scanner config;
- synthetic fixtures;
- public theme identifiers;
- research-routing code and tests.

Forbidden:

- personal holdings;
- private sizing;
- live private Decision Ledger entries;
- brokerage credentials;
- proprietary secrets.

Scheduled live monitoring remains disabled.

## 17. Module boundaries

Add focused modules:

    src/decision_lab/scanner.py
      ThemeScanObservation
      ThemeScanResult
      ScannerConfig
      rank_themes()

    src/decision_lab/research_budget.py
      ResearchTier
      ResearchAllocation
      ResearchBudgetConfig
      ResearchBudgetAllocator

    config/scanner/world_scanner_defaults.yaml
    config/policies/research_budget_defaults.yaml

    tests/test_scanner.py
    tests/test_research_budget.py

Existing modules should remain unchanged except for narrow public exports if needed.

## 18. Version 0.1 configuration

Scanner config contains source-class weights, staleness window, confidence floor, novelty floor, repeated-no-change penalty, version, and calibration_label = uncalibrated.

Budget config starts with:

    version: 0.1
    theme_research_slots: 8
    full_decision_slots: 3
    minimum_independent_sources: 1
    calibration_label: uncalibrated

Exact ranking weights live in config and are tested for deterministic application, not investment optimality.

## 19. Data flow

One cycle:

1. Load current effective ThemeRegistry state.
2. Ingest cheap multi-source ThemeScanObservation records.
3. Reject future-dated inputs.
4. Separate model output from independent evidence.
5. Aggregate component diagnostics.
6. Compare only against strictly prior scan results.
7. Compute lifecycle recommendation.
8. Compute evidence confidence and research priority.
9. Detect forced-review conditions.
10. Emit deterministic ThemeScanResult objects.
11. Pass results to ResearchBudgetAllocator.
12. Reserve forced-review capacity.
13. Allocate ordinary THEME_RESEARCH slots.
14. Allocate ordinary FULL_DECISION_RESEARCH slots.
15. Emit ResearchAllocation objects with provenance.
16. Only allocated themes proceed into existing downstream research.
17. ThemeKey/Tape/router rules remain unchanged.

## 20. Testing strategy

Version 0.1 must prove:

1. Radar/model-only strength cannot promote beyond SCAN_ONLY.
2. Radar + independent support can raise priority.
3. A strengthening theme with independent support can enter THEME_RESEARCH.
4. A sufficiently novel/high-priority strengthening theme can enter FULL_DECISION_RESEARCH.
5. An uncalibrated theme may enter full research while existing ThemeKey remains false.
6. Stale coverage lowers confidence and can prevent ordinary promotion.
7. Independent contradiction produces explicit reasons.
8. Forced review preempts a lower-priority ordinary slot.
9. Repeated-no-change decay lowers ordinary priority.
10. Forced review bypasses repeated-no-change decay.
11. Future-dated observations are rejected.
12. prior.as_of >= cycle_as_of is rejected from historical features.
13. Missing signals remain missing.
14. Same inputs produce identical ordered outputs.
15. Tie-breaking follows the documented order.
16. Scanner does not mutate ThemeRegistry.
17. Existing Tape, A-H router, hierarchical linkage, ThemeKey, and ledger tests remain unchanged.
18. No live ledger path is enabled.

Synthetic fixtures must include DataCenter_Infra, Genomics_Bio, one model-only synthetic theme, one stale theme, and one contradicting/forced-review theme.

## 21. Acceptance criteria

Increment 3 is complete when:

- ThemeScanObservation and ThemeScanResult exist as public typed interfaces;
- ResearchTier, ResearchAllocation, and ResearchBudgetAllocator exist;
- Radar/model output is structurally distinguishable from independent evidence;
- model-only strength cannot receive ordinary expensive research;
- strengthening themes with independent corroboration can receive bounded research capacity;
- forced review can preempt ordinary allocation with explicit reasons;
- repeated-no-change decay uses prior-only history;
- ranking/allocation is deterministic;
- scanner emits lifecycle recommendations without mutating ThemeRegistry;
- allocation cannot change ThemeKey permission;
- no Tape/router/linkage/ledger semantic changes are introduced;
- all existing plus new scanner/budget tests pass;
- changed-files Ruff passes;
- no live/private logging is enabled.

## 22. Deferred work

Deliberately deferred:

- ticker-first clustering and automatic theme creation;
- learned scanner weights;
- probabilistic lifecycle models;
- automatic SEC/IR crawling;
- news NLP;
- provider-specific industry taxonomies;
- cross-theme overlap optimization;
- automated scheduled execution;
- value-of-information calibration;
- portfolio sizing/execution.

These should be added only after the deterministic research-budget layer accumulates immutable allocation/outcome evidence.
