# Market-wide Theme Operating System — Design

Date: 2026-09-17
Status: proposed design approved in chat; implementation not started
Repository: `theme-radar-decision-lab`

## 1. Purpose

Generalize the current DataCenter_Infra pilot into a market-wide, theme-agnostic research operating system without copying DataCenter-specific assumptions into other industries.

The system should scan broadly, spend expensive research effort only on strengthening themes and promising expressions, and preserve the current separation between observed facts, model output, inference, Tape state, action permission, and immutable decisions.

Target pipeline:

`Raw Evidence -> Global Theme Radar -> Theme Registry / Lifecycle -> Dynamic Theme Universe -> Company Evidence Adapters -> Hierarchical Expression Diagnostics -> Tape State Machine -> Playbook Router -> Immutable Decision Ledger -> Forward Outcome Evaluation`

The existing DataCenter_Infra workflow becomes one theme package using this shared engine, not the engine's special case.

## 2. Non-goals

This version will not:

- attempt to deeply research every listed security every day;
- hard-code a permanent catalog of themes;
- assume GICS sectors are the top-level ontology;
- reuse DataCenter absolute structure thresholds as universal thresholds;
- use a ticker as part of its own control basket;
- treat Radar or Navigator outputs as ground truth;
- enable brokerage execution;
- write live private decisions into the currently public repository;
- build industry-specific valuation models for every sector in the first increment.

## 3. Architectural choice

### Considered approaches

1. **Clone the DataCenter configuration per theme.**
   Fast initially, but creates duplicated thresholds, brittle fixed universes, and silent DataCenter overfitting.

2. **Build a generic Theme Registry above the existing engine.**
   Keep the current `ThemeUniverse`, Tape, linkage, router, ledger, and outcomes concepts, while adding theme lifecycle, per-theme policy, evidence adapters, and hierarchical controls.

3. **Replace the repository with a new market-wide framework.**
   Cleaner in theory, but discards already-tested invariants and introduces unnecessary migration risk.

### Selected approach

Use approach 2. The existing engine is already largely theme-agnostic: candidate state, universe membership, Tape state, A-H routing, and append-only decisions do not inherently depend on DataCenter. The missing layer is theme discovery/onboarding and industry-aware evidence normalization.

## 4. System layers

### 4.1 World Scanner

Purpose: cheap, broad discovery across the investable market.

Responsibilities:

- ingest Radar/Navigator snapshots as model evidence only;
- ingest broad market/sector/industry price, volume, volatility, relative-strength, and dispersion features;
- ingest public event/attention/capital-flow evidence;
- propose new themes and changes to existing themes;
- update theme lifecycle evidence, not company trade permission.

The World Scanner should be able to cover thousands of securities because it performs inexpensive filtering rather than full company research.

### 4.2 Theme Registry

A theme becomes a first-class object rather than a free-form string.

Proposed fields:

```text
ThemeDefinition
  theme_id
  display_name
  aliases
  parent_theme_id
  child_theme_ids
  lifecycle_state
  discovered_at
  effective_from
  effective_to
  thesis_summary
  economic_chain_description
  benchmark_stack
  theme_key_policy
  evidence_source_policy
  provenance
  version
```

Lifecycle states:

```text
discovery
forming
strengthening
mature
weakening
dormant
retired
```

Lifecycle transitions must be evidence-backed and timestamped. Themes may split, merge, become children of broader themes, or retire. A retired theme remains queryable for historical evaluation.

### 4.3 Theme Package

Each active theme owns a package containing:

- dynamic value-chain layers;
- candidate universe;
- theme-specific controls;
- evidence adapter requirements;
- Theme-key calibration policy;
- known structural risks;
- provenance and version.

DataCenter_Infra becomes one package under this interface.

A package is configuration plus evidence, not custom execution code unless a domain truly requires a specialized adapter.

### 4.4 Dynamic Theme Universe

Reuse and extend the existing `ThemeUniverse` and `Candidate` concepts.

Candidate states remain:

```text
discovery
provisional
validated
watch_only
executable_candidate
retired
```

Expression roles remain conceptually compatible with:

```text
beta_proxy
quality_alpha
high_beta_satellite
second_order_beneficiary
weak_or_unstable
unclassified
```

Future implementation may add richer diagnostic metadata, but should not multiply categorical roles unless outcome evaluation shows a need.

Membership changes must include:

- effective timestamp;
- economic role/layer;
- confidence/evidence strength;
- primary-source provenance where available;
- reason for promotion/demotion/retirement.

New membership never retroactively changes historical theme baskets.

## 5. Company evidence normalization

Different industries expose economic reality through different KPIs. The system should not evaluate a bank, semiconductor vendor, biotech company, and industrial contractor with one fixed checklist.

Introduce a `CompanyEvidenceAdapter` interface.

Candidate adapter families for later implementation:

```text
IndustrialsAdapter
SemiconductorsAdapter
SoftwareAdapter
BanksAdapter
InsuranceAdapter
BiotechAdapter
HealthcareServicesAdapter
EnergyAdapter
UtilitiesAdapter
REITAdapter
ConsumerAdapter
CommoditiesAdapter
DefenseAdapter
```

Each adapter reads domain-relevant raw facts and emits a common normalized evidence contract:

```text
NormalizedCompanyEvidence
  growth
  margin_quality
  demand_visibility
  order_or_contract_visibility
  capital_intensity
  cash_generation
  balance_sheet_strength
  customer_concentration
  supply_constraint
  guidance_revision
  valuation_anchor_change
  thesis_risk
  source_coverage
  as_of
  provenance
```

Adapters must preserve underlying raw facts. Normalized outputs are inference, not replacements for filings/releases.

The first implementation increment should define the interface and provide only two adapters:

- a generic fallback adapter;
- an industrials/infrastructure adapter extracted from DataCenter practice.

Other adapters are added only when a strengthening theme requires them.

## 6. Hierarchical expression validity

Current leave-one-out theme controls are necessary but not sufficient for market-wide use because a ticker can move with the market, sector, industry, and theme simultaneously.

Target model:

```math
r_i = alpha_i + beta_M M + beta_S S + beta_I I + beta_T T_{-i} + epsilon_i
```

Where:

- `M` is a broad market control;
- `S` is a sector control;
- `I` is an industry control when meaningful;
- `T_{-i}` is a target-excluded dynamic theme control.

Required diagnostics:

- rolling correlation to theme control;
- theme beta after broader controls;
- partial/explanatory R² or equivalent incremental fit;
- residual/intercept behavior;
- residual volatility;
- window stability;
- decoupling/change-point indicators;
- explicit circularity warning.

A near-perfect correlation/beta is a diagnostic warning for identity or construction leakage, not automatically a high-quality expression.

Theme-control construction rules:

1. Target ticker must be excluded.
2. Controls should span multiple value-chain layers when possible.
3. No one constituent should dominate mechanically.
4. Newly added constituents only enter controls from their effective timestamp forward.
5. If a valid control cannot be constructed, linkage status is `coverage_pending`, never fabricated.

## 7. Theme Key policy

The dual-key rule remains universal:

```text
Actionable permission requires Theme key + Tape key.
One key only => WATCH_ONLY.
Failed/falling Tape => BLOCKED.
```

However, DataCenter absolute thresholds are not universal.

Introduce a `ThemeKeyPolicy` with:

```text
minimum_flow_condition
structure_policy
persistence_policy
carry_policy
minimum_valid_sessions
confidence_policy
full_permission_policy
```

Policies may use theme-relative historical percentiles rather than fixed absolute values.

For example, a theme may require:

```text
flow >= theme-specific threshold
structure percentile >= P80 of its own valid history
minimum N valid trading sessions of persistence
no raw/calibrated inconsistency above configured tolerance
```

DataCenter may continue using its existing explicit thresholds as a package-level policy until enough history exists for better calibration.

## 8. Tape and Playbook routing

The existing Tape state vocabulary and A-H router remain shared infrastructure.

No industry-specific Tape rules should be introduced unless empirical evaluation demonstrates a need.

The system continues to track path memory:

```text
falling_knife
failed_rebound
attempted_base
higher_low
reclaim
clean_retest
breakout
squeeze
extended
range
transition
```

The A-H playbooks remain universal semantic routes:

```text
A Event Breakout
B Retest Confirmation
C Mispricing after stabilization
D Compression -> Expansion
E Regime Carry
F Event Fade
G Pairs Convergence
H Structural Repricing expressed through valid Tape
NoTrade / Block
```

Future calibration may become theme-conditional, but raw routing semantics should stay stable so outcomes remain comparable.

## 9. Research-budget funnel

The system must not perform expensive research on the entire market every cycle.

Target funnel:

```text
~5000 securities
    -> broad World Scanner
~30-80 active themes
    -> lifecycle scoring
~5-15 strengthening themes
    -> dynamic company/value-chain research
~50-150 validated expressions
    -> hierarchical linkage + Tape
~10-30 interesting Tape states
    -> full router / decision review
~0-8 material Decision Objects
```

Numbers are operating targets, not hard constraints.

Promotion into more expensive stages should depend on evidence novelty and expected decision value.

## 10. Evidence provenance

Every material evidence record should track:

```text
source_type
source_name
source_timestamp
retrieved_at
as_of
observed_or_inferred
entity/theme/ticker scope
content/reference hash when available
model/config version
```

Source priority for company facts:

1. SEC/regulatory filing;
2. company earnings release / IR / investor presentation;
3. official government/industry source;
4. reputable reporting;
5. model/Radar output.

Radar/Navigator remains model evidence for Discovery and Structural Maturity only. It must not be the sole source for company membership, linkage, Tape, or action.

## 11. Decision immutability

Existing append-only decision principles remain unchanged.

A Decision Object must bind to exact versions of:

- Radar commit/blob/bundle where available;
- ThemeDefinition version;
- ThemePackage/universe version;
- evidence timestamps;
- control construction version;
- Tape/router version;
- configuration/model version.

A later recalculation creates a recomputed view. It never rewrites an earlier live decision.

Because this repository is public, live/private decisions remain disabled until privacy activation is completed.

## 12. Data model additions

First implementation increment should add only the following core types:

```text
ThemeLifecycleState
ThemeDefinition
ThemeRegistry
ThemeKeyPolicy
ThemePackage
NormalizedCompanyEvidence
CompanyEvidenceAdapter (protocol/interface)
GenericEvidenceAdapter
IndustrialsInfrastructureAdapter
HierarchicalControlSpec
HierarchicalLinkageResult
```

Existing `Candidate`, `ThemeUniverse`, Tape, playbook, ledger, and outcome interfaces should be extended compatibly rather than replaced.

## 13. Configuration layout

Target public-safe configuration layout:

```text
config/
  themes/
    datacenter_infra.yaml
    <future-theme>.yaml
  policies/
    theme_key_defaults.yaml
  adapters/
    industrials_infrastructure.yaml
```

The current `config/datacenter_seed.example.yaml` will initially remain as a compatibility fixture. Migration should not delete it until tests verify equivalent loading through the new package structure.

## 14. Data flow

One monitoring cycle:

1. Ingest latest raw/model evidence.
2. Update Theme Registry observations.
3. Detect lifecycle transitions and strengthening themes.
4. Allocate research budget to strengthening themes.
5. Refresh each selected Theme Package and Dynamic Universe.
6. Run industry-aware company evidence adapters on promoted candidates.
7. Build hierarchical target-excluded controls.
8. Run linkage diagnostics.
9. Run Tape State Machine for the strongest expressions.
10. Route A-H plus NoTrade.
11. Apply dual-key permission.
12. Emit material append-only Decision Objects only when a defined novelty threshold is crossed.
13. Later attach forward outcomes without modifying the original decision.

## 15. Failure and uncertainty handling

The system must prefer explicit missingness over synthetic certainty.

Examples:

- missing Navigator structure -> Theme key cannot use it;
- no valid theme control -> linkage `coverage_pending`;
- stale market data -> Tape cannot advance on that observation;
- incomplete filings -> source coverage warning;
- same-day historical recomputation -> append new provenance, do not overwrite;
- contradictory sources -> preserve divergence and lower confidence;
- insufficient theme history -> use conservative/default policy and mark uncalibrated.

## 16. Testing strategy

First implementation increment must add tests for:

1. Theme Registry create/update/retire lifecycle transitions.
2. Theme aliases and parent/child relationships.
3. Version/effective-time behavior.
4. Package loading for DataCenter through the new generic interface.
5. Candidate historical membership is not retroactively changed.
6. ThemeKeyPolicy does not treat DataCenter thresholds as global defaults.
7. Evidence adapter raw-vs-normalized separation.
8. Hierarchical control excludes target and rejects circular identity.
9. Missing valid controls return `coverage_pending` rather than fake metrics.
10. Existing Tape and A-H dual-key regression tests continue passing unchanged.
11. Legacy `datacenter_seed.example.yaml` remains loadable during migration.

## 17. Rollout plan

### Increment 1 — abstraction spine

Implement Theme Registry, Theme Package, ThemeKeyPolicy, evidence adapter interface, hierarchical control data types, and DataCenter compatibility loading. No new themes yet.

Success condition: DataCenter produces the same semantic universe/Tape/router behavior through the generic interface.

### Increment 2 — second real theme

Use the live Radar to select one strengthening non-DataCenter theme. Build its value chain from primary evidence and onboard it without adding custom engine logic.

Success condition: a genuinely different theme runs end-to-end through the same core engine.

### Increment 3 — World Scanner and budget funnel

Add broad discovery ranking and research-budget allocation. Only strengthening themes receive expensive company research/linkage/Tape refresh.

### Increment 4 — additional evidence adapters

Add adapters only as demanded by active themes, prioritizing semiconductors, energy/utilities, financials, and healthcare.

### Increment 5 — calibration and outcomes

Use immutable forward outcomes to calibrate theme policies and playbook scores by theme/regime. Do not calibrate on rewritten historical decisions.

## 18. Acceptance criteria for the first implementation increment

The first increment is complete when:

- DataCenter is represented as a normal `ThemePackage` registered in `ThemeRegistry`;
- no core engine function requires the literal theme name `DataCenter_Infra`;
- DataCenter package-level thresholds remain available without becoming global defaults;
- a generic evidence adapter and industrials/infrastructure adapter both emit the common evidence contract;
- hierarchical control specifications can represent market/sector/industry/theme controls with target exclusion;
- circular controls are rejected;
- missing controls stay explicitly pending;
- all existing tests pass;
- new registry/policy/adapter/control tests pass;
- no live decision logging is enabled in the public repository.

## 19. Deferred decisions

These are deliberately deferred until a second real theme exposes the need:

- exact theme discovery clustering algorithm;
- exact global number of active themes;
- industry taxonomy provider;
- sector ETF mapping source;
- adapter-specific valuation models;
- probabilistic lifecycle transition model;
- cross-theme overlap optimization;
- portfolio sizing/execution.

This prevents speculative architecture from outrunning observed research needs.
