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
    scan_priority
    effective_priority
    scan_novelty_score
    forced_review
    allocation_reasons
    source_scan_result_hash

scan_priority is copied from the current ThemeScanResult. effective_priority is the allocator-side value after any eligible repeated-no-change penalty. Forced review bypasses that penalty, so forced allocations use effective_priority = scan_priority.

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

Version 0.1 uses a deterministic engineering formula:

    coverage = min(1.0, independent_source_count / 2.0)

    agreement =
        1.0 - independent_contradiction_count
              / max(1, independent_support_count + independent_contradiction_count)

    freshness =
        mean(max(0.0, 1.0 - age_days / stale_after_days))
        over independent observations

    evidence_confidence =
        0.40 * coverage
      + 0.30 * agreement
      + 0.30 * freshness

If there are no independent observations, evidence_confidence = 0.0.

Default stale_after_days = 5 calendar days.

These values are uncalibrated research-routing defaults, not probabilities or investment thresholds.

### 7.4 Research priority

Use a configurable deterministic score.

First compute a weighted mean over available positive components only:

    base_priority =
        weighted_mean(
            discovery,
            structural,
            persistence,
            breadth,
            relative_strength,
            novelty,
            evidence_confidence
        )

Version 0.1 positive-component weights are:

    discovery = 0.15
    structural = 0.20
    persistence = 0.15
    breadth = 0.10
    relative_strength = 0.10
    novelty = 0.15
    evidence_confidence = 0.15

Penalty diagnostics are:

    contradiction_ratio =
        independent_contradiction_count
        / max(1, independent_support_count + independent_contradiction_count)

    stale_ratio =
        stale_observation_count / max(1, total_observation_count)

    contradiction_or_staleness_penalty =
        max(contradiction_ratio, stale_ratio)

    repeated_no_change_penalty =
        min(0.30, 0.10 * consecutive_no_change_cycles)

Final scanner priority is:

    research_priority =
        clip(
            base_priority
            - 0.25 * contradiction_or_staleness_penalty,
            0.0,
            1.0
        )

Missing positive components are omitted from the weighted mean rather than imputed.

Repeated-no-change decay is not applied in the scanner because the scanner does not know whether prior cycles actually consumed expensive research budget. That decay is applied later by the Research Budget Allocator using prior ResearchAllocation history.

All weights and penalty coefficients are configuration values. The shipped v0.1 values are public-safe deterministic engineering defaults labeled uncalibrated. They are never ThemeKey thresholds or probabilities.

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

Version 0.1 uses conservative deterministic recommendations:

- If current state is discovery or forming, independent_support_count >= 1, structural_score >= 0.60, persistence_score >= 0.60, and independent_contradiction_count = 0, recommend strengthening.
- If current state is strengthening or mature and contradiction_ratio >= 0.50, recommend weakening and forced review.
- If current state is strengthening or mature and both persistence_score < 0.35 and breadth_score < 0.35, recommend weakening.
- If current state is weakening and the last 3 strictly prior cycles plus the current cycle contain zero independent supporting observations, recommend dormant.
- Otherwise recommend no_change.
- Version 0.1 never recommends retired automatically.
- Split/merge recommendations are deferred.

These are lifecycle-review heuristics only. They do not mutate ThemeRegistry.

## 10. Research Budget Allocator

Public interface:

    ResearchBudgetAllocator.allocate(
        scan_results,
        registry_state,
        prior_allocations,
        config,
        cycle_as_of,
    ) -> list[ResearchAllocation]

### 10.1 Capacity controls

Initial configurable caps:

    theme_research_slots = 8
    full_decision_slots = 3

FULL_DECISION_RESEARCH is a subset of THEME_RESEARCH for capacity accounting. Every FULL_DECISION_RESEARCH allocation consumes one theme_research slot and one full_decision slot.

Forced reviews also consume both slots. They preempt ordinary allocations but do not create capacity beyond the configured caps.

These are resource limits, not empirical market truths.

### 10.2 Ordinary tier eligibility

Every theme starts SCAN_ONLY.

THEME_RESEARCH eligibility requires:

- current effective lifecycle state = strengthening;
- independent corroboration satisfied;
- evidence_confidence >= 0.45;
- remaining theme-research capacity.

FULL_DECISION_RESEARCH eligibility requires:

- THEME_RESEARCH eligibility;
- research_priority >= 0.65;
- novelty_score is present and >= 0.35;
- remaining full-decision capacity.

The values 0.45, 0.65, and 0.35 are v0.1 uncalibrated research-routing defaults and live in configuration.

ThemeCalibrationState does not control research allocation. Therefore Genomics_Bio may receive FULL_DECISION_RESEARCH while ThemeKey remains false because it is uncalibrated.

## 11. Forced review

Some events must preempt ordinary top-N ranking.

Version 0.1 has two native forced-review detectors that are representable from ThemeScanObservation and current lifecycle state:

- hard independent contradiction / major model-versus-independent divergence;
- lifecycle deterioration crossing the configured severity threshold.

Material Tape-state transitions, explicit ticker-level invalidation events, and source-integrity incidents require a separate external review-trigger input contract and are deferred from Increment 3. They must not be inferred from free-form notes.

Forced review:

- reserves a FULL_DECISION_RESEARCH slot;
- may displace the lowest-priority ordinary allocation;
- does not imply positive opportunity;
- does not change ThemeKey;
- records exact reasons and severity.

If forced-review demand exceeds capacity, sort by severity and then deterministic tie-breakers.

Forced review is available only for a known ThemeDefinition. An unknown discovery candidate cannot enter package-dependent FULL_DECISION_RESEARCH until it is explicitly registered and has a package.

## 12. Repeated-no-change decay

Do not repeatedly spend expensive budget on a theme that remains unchanged.

Decay belongs to the Research Budget Allocator, not the scanner, because only allocation history proves that expensive research budget was actually spent.

The allocator receives prior ResearchAllocation objects. For each theme, walk backward through strictly prior allocations ordered by as_of and count consecutive allocations where:

- tier is THEME_RESEARCH or FULL_DECISION_RESEARCH; and
- scan_novelty_score is present and < novelty_floor.

Stop at the first SCAN_ONLY allocation, missing novelty, or novelty >= novelty_floor.

Then compute:

    repeated_no_change_penalty =
        min(
            repeated_no_change_penalty_cap,
            repeated_no_change_penalty_per_cycle * consecutive_expensive_low_novelty_cycles
        )

For ordinary allocation:

    effective_priority =
        max(0.0, scan_priority - repeated_no_change_penalty)

For forced review:

    effective_priority = scan_priority

The penalty cannot suppress forced review, a new independent contradiction, or another forced-review condition.

Every prior allocation used for decay must satisfy prior.as_of < cycle_as_of. Same-cycle or future allocation history is rejected from decay computation.

## 13. Determinism and tie-breaking

Given identical observations, registry state, prior results, config, and cycle_as_of, return identical ordered outputs.

Tie-break order:

1. forced review before ordinary allocation;
2. higher forced-review severity;
3. higher effective priority;
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

Scanner config contains source-class weights, staleness window, component weights, contradiction/staleness penalty coefficients, lifecycle recommendation gates, version, and calibration_label = uncalibrated.

Version 0.1 source-class weights are:

    sec_filing: 1.00
    company_ir: 1.00
    official_macro: 1.00
    industry_primary: 0.95
    market_data: 0.90
    reputable_reporting: 0.75
    derived_feature: 0.60
    radar_model_output: 0.50

Version 0.1 scanner defaults include:

    stale_after_days: 5
    confidence_floor: 0.45
    strengthening_structure_gate: 0.60
    strengthening_persistence_gate: 0.60
    weakening_low_persistence_gate: 0.35
    weakening_low_breadth_gate: 0.35
    hard_contradiction_ratio: 0.50
    dormant_no_support_cycles: 3
    calibration_label: uncalibrated

Budget config starts with:

    version: 0.1
    theme_research_slots: 8
    full_decision_slots: 3
    minimum_independent_sources: 1
    confidence_floor: 0.45
    full_priority_gate: 0.65
    full_novelty_gate: 0.35
    novelty_floor: 0.20
    repeated_no_change_penalty_per_cycle: 0.10
    repeated_no_change_penalty_cap: 0.30
    calibration_label: uncalibrated

Positive-component weights are discovery 0.15, structural 0.20, persistence 0.15, breadth 0.10, relative_strength 0.10, novelty 0.15, and evidence_confidence 0.15. The contradiction/staleness penalty coefficient is 0.25.

All shipped values are tested for deterministic application, not investment optimality.

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
11. Load strictly prior ResearchAllocation history for budget-decay computation.
12. Pass current scan results plus prior allocations to ResearchBudgetAllocator.
13. Compute allocator-side effective priority from actual prior expensive-research history.
14. Reserve forced-review capacity.
15. Allocate ordinary THEME_RESEARCH slots.
16. Allocate ordinary FULL_DECISION_RESEARCH slots.
17. Emit ResearchAllocation objects with provenance.
18. Only allocated themes proceed into existing downstream research.
19. ThemeKey/Tape/router rules remain unchanged.

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
9. Repeated-no-change decay lowers ordinary effective priority only when prior expensive allocations actually occurred.
10. A low-novelty prior SCAN_ONLY cycle does not create repeated-no-change decay.
11. Forced review bypasses repeated-no-change decay.
12. Future-dated observations are rejected.
13. prior scan-result as_of >= cycle_as_of is rejected from scanner historical features.
14. prior allocation as_of >= cycle_as_of is rejected from allocator decay history.
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
- repeated-no-change decay uses strictly prior ResearchAllocation history and only counts prior expensive allocations;
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
- external forced-review trigger inputs for material Tape transitions, explicit invalidation events, and source-integrity incidents;
- value-of-information calibration;
- portfolio sizing/execution.

These should be added only after the deterministic research-budget layer accumulates immutable allocation/outcome evidence.
