# Increment 5 — End-to-End Replay Cycle Design

Date: 2026-09-19
Status: approved in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: feature/end-to-end-replay-cycle

## 1. Purpose

Define one deterministic, auditable research-allocation replay cycle that composes the already-existing market observation adapter, World Scanner, and Research Budget Allocator without inventing new decision semantics.

Target flow:

    frozen replay inputs
      -> MarketObservationAdapter
      -> combined independent + model observations
      -> World Scanner
      -> Research Budget Allocator
      -> ReplayCycleResult

Increment 5 proves that the current market-wide evidence-routing stack can be replayed end-to-end from frozen evidence into bounded research allocations.

It does not perform the downstream expensive research implied by FULL_DECISION_RESEARCH.

## 2. Core invariant

The replay layer is orchestration only.

It may:

- call adapt_market_observations;
- call rank_themes;
- call ResearchBudgetAllocator.allocate;
- construct deterministic audit records and hashes.

It may not:

- fetch network data;
- mutate ThemeRegistry;
- mutate ThemePackage or ThemeUniverse;
- evaluate or upgrade ThemeKey;
- run company deep research;
- run hierarchical linkage;
- run Tape;
- run A-H routing;
- write ledger/live or recomputed;
- write reports;
- schedule jobs;
- place brokerage orders.

The orchestrator must not repair, reinterpret, or override failures from downstream components.

## 3. Selected architecture

Use a pure function-style replay orchestrator.

New module:

    src/decision_lab/replay.py

Public interface:

    run_replay_cycle(
        replay_input: ReplayCycleInput,
    ) -> ReplayCycleResult

The module has no filesystem or network side effects.

CLI/file serialization is deferred.

## 4. Alternatives considered

### A. Pure Replay Orchestrator — selected

The replay core consumes already-loaded Python objects and returns a typed result.

Advantages:

- deterministic;
- testable without filesystem/network;
- preserves current component boundaries;
- easy to hash and compare;
- future CLI/workflow wrappers remain thin.

### B. CLI/file-first replay

A script loads YAML/JSON and writes a report.

Rejected for Increment 5 because it mixes replay semantics with paths, serialization, and user interface decisions before the core contract is stable.

### C. DAG/workflow engine

A stage graph adds caching, persistence, retries, and artifact stores.

Rejected as premature. Increment 5 needs one trustworthy deterministic cycle, not a workflow platform.

## 5. Scope boundary

Increment 5 ends at research allocation:

    ThemeScanResult
      -> ResearchAllocation

FULL_DECISION_RESEARCH means:

    this theme is permitted to enter the next expensive research layer

It does not mean:

    company/linkage/Tape/router research has already run

No downstream decision or trade artifact is created.

## 6. Input model

### 6.1 ThemeReplayInput

One registered theme's market-evidence input:

    ThemeReplayInput
      package: ThemePackage
      market_spec: MarketObservationSpec
      market_config: MarketObservationConfig
      bars: tuple[MarketBar, ...]
      market_source_ref: str

Rules:

- package.definition.theme_id must equal market_spec.theme_id;
- each registered theme may appear at most once;
- package definition must be effective at cycle_as_of;
- market_source_ref must be non-empty;
- bars may contain unrelated symbols because the market adapter already ignores semantically unused rows.

### 6.2 ReplayCycleInput

    ReplayCycleInput
      cycle_as_of: str
      themes: tuple[ThemeReplayInput, ...]
      external_observations: tuple[ThemeScanObservation, ...]
      prior_scan_results: tuple[ThemeScanResult, ...]
      prior_allocations: tuple[ResearchAllocation, ...]
      scanner_config: ScannerConfig
      budget_config: ResearchBudgetConfig

external_observations is the generic frozen non-market input channel.

Typical use:

- Radar/model output enters as ThemeScanObservation with source_type = radar_model_output and is_independent = false;
- other already-normalized external evidence may also enter if it satisfies the scanner contract.

Increment 5 does not add a Radar adapter.

## 7. Registered versus unknown themes

Registered theme IDs come only from ThemeReplayInput packages.

The replay registry mapping is:

    {
        package.definition.theme_id: package.definition
    }

Unknown themes are allowed only through external_observations.

The orchestrator never creates a ThemeDefinition for them.

Therefore:

    unknown + model-only observation
      -> scanner result may exist
      -> allocator sees theme not registered
      -> SCAN_ONLY

This preserves Increment 3 behavior.

## 8. Package effective-date validation

A supplied package must itself be active at the replay cycle.

ThemeDefinition effective windows are half-open:

    effective_from <= cycle_date < effective_to

If package.definition is not effective at cycle_as_of:

    raise ValueError("theme package not effective at cycle_as_of")

cycle_date is derived deterministically:

- if cycle_as_of is date-only, use that date directly;
- otherwise parse the ISO timestamp, normalize it to UTC, and use the resulting UTC date.

Version 0.1 expects ThemeDefinition effective_from/effective_to to be ISO date strings, matching current repository theme packages.

A future package may not participate in an earlier replay.

## 9. Canonical ordering

Input order must not affect the result.

Before orchestration, canonical-sort:

### ThemeReplayInput

    package.definition.theme_id

### external_observations

    (
        theme_id,
        as_of,
        source_ref,
        canonical_hash(asdict(observation))
    )

### prior_scan_results

    (
        theme_id,
        as_of,
        canonical_hash(asdict(result))
    )

### prior_allocations

    (
        theme_id,
        as_of,
        canonical_hash(asdict(allocation))
    )

MarketBar row ordering is already normalized by MarketObservationAdapter.

Output tuples are also deterministic.

## 10. Market stage

For each ThemeReplayInput in lexical theme_id order:

    batch = adapt_market_observations(
        package=theme_input.package,
        bars=theme_input.bars,
        spec=theme_input.market_spec,
        config=theme_input.market_config,
        cycle_as_of=replay_input.cycle_as_of,
        market_source_ref=theme_input.market_source_ref,
    )

Store all batches in lexical theme_id order.

Do not treat COVERAGE_PENDING as an exception.

The adapter decides whether a batch emits zero, one, or multiple ThemeScanObservation objects.

## 11. Combined observation stage

Construct:

    combined_observations =
        all market_batch.observations
        + external_observations

Then canonical-sort by:

    (
        theme_id,
        as_of,
        source_ref,
        canonical_hash(asdict(observation))
    )

No observation is synthesized to fill missing market coverage.

No model observation is upgraded to independent.

## 12. Scanner stage

Build registry_state only from registered packages.

Then call:

    scan_results = rank_themes(
        combined_observations,
        registry_state,
        prior_scan_results,
        scanner_config,
        cycle_as_of=cycle_as_of,
    )

The replay layer does not catch and reinterpret scanner validation failures.

Examples:

- future observation -> ValueError propagates;
- source metadata conflict -> ValueError propagates;
- invalid prior history -> ValueError propagates.

## 13. Budget stage

Call:

    allocations = ResearchBudgetAllocator().allocate(
        scan_results,
        registry_state,
        prior_allocations,
        budget_config,
        cycle_as_of=cycle_as_of,
    )

The replay layer does not alter:

- confidence gates;
- capacity;
- forced-review priority;
- repeated-no-change decay;
- unknown-theme SCAN_ONLY behavior.

## 14. Replay status

### ReplayStatus

Exactly:

    ROUTED = "routed"
    NO_OBSERVATION = "no_observation"

ROUTED means:

    a ThemeScanResult and ResearchAllocation exist for the theme

NO_OBSERVATION means:

    the theme is present in the replay theme universe
    but no observation reached the scanner for that theme

NO_OBSERVATION is not equivalent to SCAN_ONLY.

SCAN_ONLY is a real allocator output after a scan result exists.

## 15. ReplayThemeRecord

One record per theme in the union of:

- registered theme IDs;
- theme IDs present in external_observations.

Fields:

    ReplayThemeRecord
      theme_id: str
      registered: bool
      market_batch: MarketObservationBatch | None
      scan_result: ThemeScanResult | None
      allocation: ResearchAllocation | None
      replay_status: ReplayStatus

Rules:

### Registered theme + market/model observations

If scanner emits a result:

    status = ROUTED

### Registered theme + market COVERAGE_PENDING + no external observation

    market_batch exists
    scan_result = None
    allocation = None
    status = NO_OBSERVATION

### Unknown external theme

    registered = false
    market_batch = None
    scan_result exists
    allocation normally SCAN_ONLY
    status = ROUTED

No fake allocation is created for NO_OBSERVATION.

## 16. ReplayCycleResult

    ReplayCycleResult
      cycle_as_of: str

      market_batches: tuple[MarketObservationBatch, ...]
      combined_observations: tuple[ThemeScanObservation, ...]

      scan_results: tuple[ThemeScanResult, ...]
      allocations: tuple[ResearchAllocation, ...]

      theme_records: tuple[ReplayThemeRecord, ...]

      input_hash: str
      result_hash: str

All tuples use deterministic order.

### Ordering

market_batches:

    theme_id

combined_observations:

    theme_id, as_of, source_ref, observation hash

scan_results:

    theme_id

allocations:

    theme_id

theme_records:

    theme_id

The orchestrator may reorder scanner/budget outputs into lexical theme order for the replay artifact without changing their content.

## 17. Definition and universe semantic hashes

Do not hash whole dataclasses merely because they are available.

The replay input hash should bind fields that affect this replay's behavior or audit identity, while ignoring display/annotation fields that the current pipeline never reads.

### 17.1 Theme definition semantic payload

Use:

    definition_semantic_payload =
      {
        "theme_id": definition.theme_id,
        "lifecycle_state": definition.lifecycle_state.value,
        "effective_from": definition.effective_from,
        "effective_to": definition.effective_to,
        "version": definition.version,
        "provenance": list(definition.provenance),
      }

Then:

    definition_semantic_hash =
        canonical_hash(definition_semantic_payload)

Do not bind current replay hashing to:

- display_name;
- aliases;
- parent/child metadata;
- thesis_summary;
- economic_chain_description;
- benchmark_stack.

Those fields do not affect MarketObservationAdapter, Scanner, ResearchBudgetAllocator, or package-active validation in Increment 5.

### 17.2 Universe semantic payload

Do not rely only on ThemeUniverse.version.

Use:

    universe_semantic_payload =
      {
        "theme": universe.theme,
        "version": universe.version,
        "layers": [
            layer.name
            sorted lexically
        ],
        "candidates": [
            {
              "ticker": candidate.ticker.upper(),
              "theme": candidate.theme,
              "layer": candidate.layer,
              "membership_state": candidate.membership_state,
              "effective_from": candidate.effective_from,
              "effective_to": candidate.effective_to,
              "provenance": list(candidate.provenance),
            }
            sorted by uppercase ticker
        ]
      }

Then:

    universe_semantic_hash =
        canonical_hash(universe_semantic_payload)

Exclude:

- universe.generated_at;
- ThemeLayer.description;
- Candidate.expression_role;
- Candidate.economic_exposure;
- Candidate.evidence_strength;
- Candidate.notes.

Those fields are not read by the Increment-5 replay path.

If a future replay stage begins using one of them, that field must be added to the semantic payload in the same increment.

## 18. Theme replay semantic payload

For each registered ThemeReplayInput, derive:

    theme_replay_semantic_payload =
      {
        "theme_id": ...,
        "definition_semantic_hash": ...,
        "package_version": package.version,
        "universe_version": package.universe.version,
        "universe_semantic_hash": ...,
        "market_spec_hash": market_batch.spec_hash,
        "market_config_hash": market_batch.config_hash,
        "market_input_hash": market_batch.input_hash,
        "market_source_ref": market_source_ref,
      }

Do not include:

- package.source_path;
- universe.generated_at;
- unrelated unused raw bars;
- definition/universe annotation fields explicitly excluded above.

package.source_path is an I/O location, not replay semantics.

## 19. Replay input hash

ReplayCycleResult.input_hash is computed only after the market adapter stage because the adapter determines which raw bars were semantically used.

Build:

    input_payload =
      {
        "cycle_as_of": cycle_as_of,

        "registered_themes": [
            theme_replay_semantic_payload
            sorted by theme_id
        ],

        "external_observations": [
            asdict(observation)
            in canonical observation order
        ],

        "prior_scan_results": [
            asdict(result)
            in canonical prior order
        ],

        "prior_allocations": [
            asdict(allocation)
            in canonical prior order
        ],

        "scanner_config": asdict(scanner_config),
        "budget_config": asdict(budget_config),
      }

Then:

    input_hash = canonical_hash(input_payload)

This means:

- unrelated unused raw market bars do not change replay input_hash;
- changing actual used market data changes input_hash;
- changing universe content changes input_hash even if version is accidentally unchanged;
- changing package source_path does not change input_hash;
- input ordering does not change input_hash.

## 20. Replay result hash

Avoid self-reference.

Construct result payload with result_hash omitted:

    result_payload =
      {
        "cycle_as_of": cycle_as_of,
        "input_hash": input_hash,
        "market_batches": [...],
        "combined_observations": [...],
        "scan_results": [...],
        "allocations": [...],
        "theme_records": [...],
      }

Then:

    result_hash = canonical_hash(result_payload)

Identical semantic input must produce identical result_hash.

## 21. Replay purity

run_replay_cycle must not:

- read files;
- write files;
- inspect environment variables;
- call time.now;
- generate random IDs;
- call network clients;
- call GitHub;
- mutate inputs.

All required context is passed in ReplayCycleInput.

The function is deterministic under identical semantic input.

## 22. Failure handling

### Duplicate registered theme

If two ThemeReplayInput objects have the same package.definition.theme_id:

    raise ValueError("duplicate replay theme")

No silent overwrite.

### Theme/spec mismatch

Propagate adapter validation error.

### Package inactive at cycle

Raise:

    ValueError("theme package not effective at cycle_as_of")

### Market coverage pending

Do not raise.

Use the returned MarketObservationBatch.

### Market coverage pending + model observation exists

The model observation may still reach scanner.

Normal scanner/budget rules decide the result.

### Market coverage pending + no external observation

Theme record becomes NO_OBSERVATION.

### Unknown model-only theme

Scanner may produce a result.

Allocator should return SCAN_ONLY because theme is not registered.

### Invalid/future external observation

Propagate scanner ValueError.

### Invalid prior scan/allocation history

Propagate scanner/allocator ValueError.

The replay layer never downgrades hard validation errors into warnings.

## 23. First end-to-end acceptance fixture

Use synthetic/public-safe frozen inputs.

No network calls.

cycle_as_of:

    2026-09-19

### 23.1 DataCenter_Infra

Registered package.

Pinned synthetic basket bars yield:

- weak breadth;
- negative benchmark-relative return;
- independent CONTRADICTING market observation.

External Radar observation:

- model-only;
- positive discovery signal.

Expected chain:

    raw bars
      -> MarketObservationAdapter
      -> CONTRADICTING derived independent observation
      -> combined with Radar observation
      -> Scanner forced_review
      -> FULL_DECISION_RESEARCH

Interpretation:

    FULL is risk/reassessment routing, not bullish permission

### 23.2 Genomics_Bio

Registered package.

Use current real package semantics where seed members are effective from 2026-09-18.

The acceptance replay uses configured PROXY mode:

- ARKG-like synthetic proxy -> SUPPORTING;
- XBI-like synthetic proxy -> NEUTRAL.

Expected chain:

    proxy bars
      -> independent proxy observations
      -> Scanner
      -> FULL_DECISION_RESEARCH

ThemeKey remains uncalibrated and untouched.

A separate existing Increment-4 regression already proves that direct retroactive member-basket construction fails closed.

### 23.3 Rates

No ThemeReplayInput package.

External Radar/model observation only.

Expected:

    registered = false
    scan_result exists
    allocation = SCAN_ONLY
    replay_status = ROUTED

### 23.4 Registered no-observation theme

Include a synthetic registered theme whose market adapter returns COVERAGE_PENDING and which has no external observation.

Expected:

    market_batch exists
    scan_result = None
    allocation = None
    replay_status = NO_OBSERVATION

This proves NO_OBSERVATION is distinct from SCAN_ONLY.

## 24. Determinism acceptance tests

Version 0.1 must prove all of these leave input_hash, result_hash, and semantic result content unchanged:

1. reverse ThemeReplayInput order;
2. reverse raw MarketBar row order;
3. reverse external_observations order;
4. reverse prior_scan_results order;
5. reverse prior_allocations order;
6. add unrelated unused bars to a theme's bar tuple;
7. change ThemeUniverse.generated_at only;
8. change ThemePackage.source_path only;
9. change Candidate.notes/expression_role/economic_exposure/evidence_strength only;
10. change ThemeDefinition display_name/thesis_summary only.

And all of these must change input_hash:

11. change a used bar close;
12. change a candidate effective_from/effective_to;
13. change a candidate provenance field;
14. change ThemeDefinition lifecycle_state;
15. change ThemeDefinition effective_from/effective_to;
16. change scanner config;
17. change budget config;
18. change an external observation payload;
19. change prior allocation history.

## 25. Functional acceptance tests

Version 0.1 must prove:

1. duplicate replay theme is rejected;
2. inactive future package is rejected;
3. market adapter errors propagate;
4. scanner errors propagate;
5. allocator errors propagate;
6. coverage pending is not treated as exception;
7. registered coverage-pending/no-external theme becomes NO_OBSERVATION;
8. registered theme with only external model evidence can still be scanned;
9. unknown model-only theme becomes SCAN_ONLY, not NO_OBSERVATION;
10. DataCenter contradictory market evidence routes forced FULL research;
11. Genomics proxy evidence routes FULL research under current research gates;
12. ThemeKey remains unchanged;
13. no package/universe mutation occurs;
14. market_as_of may be earlier than cycle_as_of;
15. allocation.as_of remains cycle_as_of;
16. result tuples are lexically deterministic;
17. result_hash binds full replay output;
18. no filesystem/network side effects occur;
19. existing full regression remains green;
20. changed-files Ruff passes.

## 26. Proposed module boundaries

Create:

    src/decision_lab/replay.py

Create tests:

    tests/test_replay.py

Modify only for public exports:

    src/decision_lab/__init__.py

Do not modify behavior in:

    src/decision_lab/market_observation.py
    src/decision_lab/scanner.py
    src/decision_lab/research_budget.py
    src/decision_lab/themes.py
    src/decision_lab/universe.py
    src/decision_lab/tape.py
    src/decision_lab/playbooks.py
    src/decision_lab/hierarchical.py
    src/decision_lab/ledger.py

If implementation reveals a required semantic change in those modules, stop and upgrade scope rather than silently editing them.

## 27. Public repository safety

Replay fixtures may contain:

- synthetic bars;
- public ticker symbols;
- public-safe Radar-like synthetic observations;
- public configuration;
- deterministic hashes.

Do not include:

- personal holdings;
- private position sizes;
- brokerage credentials;
- proprietary licensed raw market payloads;
- live private Decision Objects.

The replay result is a research-routing artifact, not a portfolio or trading artifact.

## 28. Deferred work

Deliberately deferred:

- CLI wrapper;
- JSON/YAML replay serialization;
- report writer;
- persistent replay artifact store;
- caching;
- scheduled replay execution;
- live Radar ingestion;
- live market-data ingestion;
- company evidence refresh;
- linkage execution;
- Tape execution;
- A-H routing;
- Decision Ledger writes;
- outcome evaluation;
- portfolio sizing/execution.

These should be layered on only after ReplayCycleResult is stable and reproducible.

## 29. Completion criteria

Increment 5 is complete when:

- ReplayCycleInput and ThemeReplayInput exist;
- ReplayStatus, ReplayThemeRecord, ReplayCycleResult exist;
- run_replay_cycle is pure and deterministic;
- registered packages are validated against cycle date;
- unknown model-only themes remain supported without registration;
- NO_OBSERVATION is distinct from SCAN_ONLY;
- semantic universe hashing ignores generated_at but binds real content;
- replay input hash binds only semantic inputs;
- replay result hash binds complete outputs;
- DataCenter/Genomics/Rates/no-observation end-to-end fixtures pass;
- input-order invariance passes;
- unused-bar and nonsemantic-metadata invariance passes;
- forbidden downstream modules remain unchanged;
- all existing + new tests pass;
- changed-files Ruff passes.


## 30. Replay input validation details

Additional fail-closed validation:

- cycle_as_of must parse as ISO date or ISO datetime;
- ThemeReplayInput.market_source_ref must be non-empty after strip;
- package.definition.theme_id must be non-empty;
- duplicate registered theme IDs are rejected before any adapter call;
- ReplayCycleInput may contain zero registered themes if external observations exist;
- an entirely empty replay (no registered themes and no external observations) is valid and returns empty stage tuples plus deterministic hashes;
- prior history alone does not create a current ReplayThemeRecord.
