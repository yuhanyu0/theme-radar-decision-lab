# Increment 4 — Market Observation Adapter Design

Date: 2026-09-19
Status: approved direction in chat; implementation not started
Repository: theme-radar-decision-lab
Branch: feature/market-observation-adapter

## 1. Purpose

Turn raw, timestamped market bars into reproducible independent ThemeScanObservation records.

Increment 3 starts from ThemeScanObservation. The first real-data dry run on 2026-09-19 showed that the missing production boundary is:

    raw market bars
      + effective-dated ThemePackage membership
      + declared benchmark/proxies
      -> raw market diagnostics
      -> normalized scanner signals
      -> ThemeScanObservation

The dry run had to construct breadth, relative strength, persistence, novelty, and support direction manually. Increment 4 makes that transformation typed, versioned, deterministic, replayable, and provider-agnostic.

This adapter allocates evidence to the scanner. It does not create trade permission.

## 2. Empirical motivation from the 2026-09-19 dry run

The diagnostic run used the 2026-09-18 close because 2026-09-19 was Saturday.

DataCenter_Infra:
- current 5-session equal-weight basket return: about -2.53%;
- SPY: about -0.33%;
- excess: about -2.20 percentage points;
- positive-member breadth: 13.6%;
- prior-window excess: about +4.51 percentage points;
- current evidence therefore contradicted the recent positive regime and correctly triggered a forced research review.

Genomics_Bio:
- its seed members were only admitted effective 2026-09-18;
- retrospectively computing a five-session member basket would violate the effective-date invariant;
- declared external proxies were therefore used:
  - ARKG: about +13.77 percentage points excess vs SPY, 5/5 session outperformance;
  - XBI: about +0.61 percentage points excess vs SPY, 3/5 session outperformance;
- this gave independent corroboration without retroactively inventing Genomics membership history.

The dry run report is reports/world_scan_dry_run_2026-09-19.md.

## 3. Core invariants

1. Provider independence
   - core code consumes normalized bar records;
   - it does not import Alpaca, Yahoo, Polygon, Bloomberg, or any network client.

2. Effective-date integrity
   - a candidate may never contribute to a basket metric before effective_from;
   - a retired/effective_to candidate may not contribute after its effective window.

3. No composition-as-novelty
   - current-vs-prior novelty must be computed on a stable comparison cohort that is eligible in both windows;
   - if that stable cohort is too small, novelty is None.

4. Raw diagnostics survive normalization
   - the adapter preserves raw return/breadth/persistence/coverage diagnostics alongside normalized scanner signals.

5. Missingness is explicit
   - insufficient market history or membership coverage yields coverage_pending diagnostics and missing signals;
   - missing data are never silently imputed as zero or one.

6. Derived evidence stays derived
   - adapter outputs use source_type = derived_feature;
   - underlying market-data provenance is retained in evidence_refs and hashes.

7. Research evidence does not become permission
   - the adapter does not mutate ThemeRegistry;
   - it does not evaluate ThemeKey;
   - it does not alter Tape, A-H routing, ledger, or execution.

## 4. Non-goals

Increment 4 will not:

- fetch live market data;
- add provider credentials;
- schedule jobs;
- change the scanner scoring formula;
- change research-budget allocation;
- change ThemeKey calibration;
- change Tape or playbook routing;
- infer new themes from ticker clustering;
- automatically choose benchmark/proxy instruments;
- backfill historical theme membership;
- optimize normalization thresholds from outcomes;
- write live/private decisions;
- perform brokerage execution.

## 5. Architecture

Add one focused module:

    src/decision_lab/market_observation.py

It contains:

    MarketBar
    MarketObservationMode
    MarketObservationStatus
    MarketObservationSpec
    MarketObservationConfig
    MarketObservationDiagnostics
    MarketObservationBatch
    adapt_market_observations(...)
    load_market_observation_config(...)
    load_market_observation_spec(...)

Configuration:

    config/adapters/market_observation_defaults.yaml
    config/market_observations/datacenter_infra.yaml
    config/market_observations/genomics_bio.yaml

Tests:

    tests/test_market_observation.py

Existing modules should remain unchanged except for narrow public exports in src/decision_lab/__init__.py.

## 6. Input model

### 6.1 MarketBar

A provider-neutral daily close record:

    MarketBar
      symbol: str
      session_date: str
      available_at: str
      close: float

session_date is the explicit YYYY-MM-DD trading-session identifier after provider-specific ingestion has normalized its timestamp. available_at is the ISO 8601 time at which this bar is considered knowable to the research system.

Rules:

- symbol is normalized to uppercase;
- session_date must parse as an ISO date;
- available_at must parse as ISO 8601;
- naive available_at values are interpreted as UTC, matching existing scanner conventions;
- close must be finite and strictly positive;
- duplicate (symbol, session_date) rows are rejected for semantically used symbols, even if values match;
- a semantically used bar with available_at later than cycle_as_of is rejected as potential look-ahead;
- date-only cycle_as_of means end-of-day UTC, matching the scanner convention;
- input ordering must not affect results.

Separating session_date from available_at prevents provider timestamp conventions from silently changing effective-membership dates or look-ahead semantics.

Version 0.1 uses daily closes only.

Open/high/low/volume can be added later if a specific scanner feature requires them.

### 6.2 Market source provenance

The adapter call receives:

    market_source_ref: str

Examples:

    alpaca:iex:daily:2026-09-18
    polygon:daily:2026-09-18
    fixture:world-scan-2026-09-19

The adapter itself never interprets provider semantics.

## 7. Market observation spec

### 7.1 MarketObservationMode

Exactly:

    BASKET
    PROXY

### 7.2 MarketObservationSpec

Fields:

    theme_id
    mode
    benchmark
    proxies
    current_return_sessions
    prior_return_sessions
    min_basket_members
    version

Default window contract:

    current_return_sessions = 5
    prior_return_sessions = 5
    min_basket_members = 3

A five-session return window requires six benchmark session closes. Current and prior adjacent five-session windows require eleven benchmark session closes total.

### 7.3 Theme-specific specs

DataCenter_Infra:

    theme_id: DataCenter_Infra
    mode: basket
    benchmark: SPY
    proxies: []
    current_return_sessions: 5
    prior_return_sessions: 5
    min_basket_members: 3

Genomics_Bio:

    theme_id: Genomics_Bio
    mode: proxy
    benchmark: SPY
    proxies: [ARKG, XBI]
    current_return_sessions: 5
    prior_return_sessions: 5
    min_basket_members: 3

The proxy list is explicit configuration. The adapter must never discover or substitute proxies automatically.

## 8. Adapter configuration

MarketObservationConfig contains only versioned transformation rules.

Version 0.1 defaults:

    version: 0.1
    calibration_label: uncalibrated

    relative_strength_scale: 0.20
    novelty_scale: 0.10

    basket_support_excess_min: 0.02
    basket_support_breadth_min: 0.60
    basket_contradiction_excess_max: -0.02
    basket_contradiction_breadth_max: 0.25

    proxy_support_excess_min: 0.02
    proxy_support_persistence_min: 0.60
    proxy_contradiction_excess_max: -0.02
    proxy_contradiction_persistence_max: 0.40

All values are uncalibrated research-routing defaults.

They are not probabilities, trading thresholds, ThemeKey thresholds, or claims about optimal investment behavior.

## 9. Session calendar and window selection

The declared benchmark defines the session calendar.

Given benchmark closes available by cycle_as_of:

1. sort benchmark bars by session_date;
2. reject any required benchmark bar whose available_at exceeds cycle_as_of;
3. take the latest available benchmark session_date as market_as_of;
3. require enough sessions for current and prior windows;
4. current window start is current_return_sessions intervals before market_as_of;
5. prior window end equals current window start;
6. prior window start is prior_return_sessions intervals before prior end.

If the benchmark does not provide enough history:

    status = coverage_pending
    observations = ()
    reason includes insufficient benchmark history

No calendar-day interpolation is allowed.

## 10. BASKET mode

BASKET mode derives one independent observation for the theme.

### 10.1 Current eligible cohort

A candidate is eligible for the current full-window basket only when:

- it is effective at current-window start;
- it remains effective through current-window end;
- it has a close at both window endpoints;
- it has every benchmark session close required for daily persistence calculation.

Candidates admitted after current-window start are excluded from all current full-window basket statistics.

This is intentionally conservative.

### 10.2 Current basket return

For each eligible current member:

    member_return_i =
        close_i(current_end) / close_i(current_start) - 1

Then:

    basket_current_return =
        arithmetic_mean(member_return_i)

### 10.3 Breadth

    breadth =
        positive current-window member returns
        / current eligible member count

A zero return is not positive.

### 10.4 Persistence

For each current benchmark interval:

1. compute each current eligible member's one-session return;
2. arithmetic-mean those member returns;
3. compute the benchmark's one-session return;
4. mark 1 if theme basket return > benchmark return, else 0.

Then:

    persistence =
        outperforming intervals / valid intervals

The current eligible cohort is held fixed across the current persistence window.

### 10.5 Current excess return

    current_excess_return =
        basket_current_return - benchmark_current_return

### 10.6 Stable comparison cohort for novelty

Novelty must not be produced by membership composition changes.

Define the stable cohort as candidates that:

- are effective at prior-window start;
- remain effective through current-window end;
- have all required bars for both windows.

Use this same stable cohort to compute stable prior and current basket returns and excess returns.

Then:

    novelty_abs_excess_change =
        abs(stable_current_excess_return - stable_prior_excess_return)

If stable cohort size < min_basket_members:

    novelty_abs_excess_change = None
    novelty_signal = None
    warning includes insufficient stable comparison cohort

Current breadth/current excess may still be valid even if novelty is unavailable.

### 10.7 Membership-change diagnostics

Diagnostics record:

    current_member_symbols
    stable_member_symbols
    current_member_count
    stable_member_count
    membership_changed

membership_changed is true when current cohort differs from stable cohort.

## 11. PROXY mode

PROXY mode emits one independent ThemeScanObservation per declared proxy.

For each proxy:

1. use the same benchmark session windows;
2. require proxy closes for every benchmark session needed;
3. compute current proxy return, current benchmark return, current excess return, daily persistence, prior proxy excess return, and absolute change in excess return.

Breadth is not defined for a single proxy:

    breadth = None
    breadth_signal = None

A missing or incomplete proxy produces one coverage_pending diagnostic and no observation for that proxy.

Other valid proxies may still emit observations.

If all proxies are unavailable:

    observations = ()

The adapter never substitutes another proxy.

## 12. Raw diagnostics

### 12.1 MarketObservationStatus

Exactly:

    READY
    COVERAGE_PENDING

### 12.2 MarketObservationDiagnostics

One diagnostic object per emitted/attempted basket or proxy source.

Fields:

    theme_id
    mode
    instrument
    benchmark
    market_as_of

    current_start
    current_end
    prior_start
    prior_end

    status
    reason

    current_return
    benchmark_current_return
    current_excess_return

    prior_excess_return
    novelty_abs_excess_change

    breadth
    persistence

    current_member_symbols
    stable_member_symbols
    current_member_count
    stable_member_count
    membership_changed

    support_direction

    relative_strength_signal
    breadth_signal
    persistence_signal
    novelty_signal

    universe_version
    package_version
    spec_version
    config_version

    input_hash
    spec_hash
    config_hash
    diagnostic_hash

    evidence_refs
    warnings

For PROXY mode:
- current/stable member fields are empty/zero;
- membership_changed is false.

For coverage-pending cases:
- computable provenance/window fields remain populated;
- unavailable metrics remain None.

## 13. Normalization

### 13.1 Relative strength

    relative_strength_signal =
        clip(
            0.5 + current_excess_return / relative_strength_scale,
            0,
            1
        )

With v0.1 scale = 0.20:
- zero excess -> 0.50;
- +20 percentage points -> 1.00;
- -20 percentage points -> 0.00.

### 13.2 Breadth

In BASKET mode:

    breadth_signal = breadth

In PROXY mode:

    breadth_signal = None

### 13.3 Persistence

    persistence_signal = persistence

### 13.4 Novelty

When prior-current comparison is valid:

    novelty_signal =
        clip(
            novelty_abs_excess_change / novelty_scale,
            0,
            1
        )

Otherwise:

    novelty_signal = None

### 13.5 Discovery / structure / volatility

Version 0.1 does not infer these from price bars:

    discovery_signal = None
    structure_signal = None
    volatility_signal = None

The adapter must not manufacture them.

## 14. Support direction

Support direction is deterministic and mode-specific.

### 14.1 BASKET mode

SUPPORTING iff:

    current_excess_return >= basket_support_excess_min
    AND breadth >= basket_support_breadth_min

CONTRADICTING iff:

    current_excess_return <= basket_contradiction_excess_max
    AND breadth <= basket_contradiction_breadth_max

Otherwise:

    NEUTRAL

With v0.1 defaults this reproduces the qualitative DataCenter dry-run contradiction.

### 14.2 PROXY mode

SUPPORTING iff:

    current_excess_return >= proxy_support_excess_min
    AND persistence >= proxy_support_persistence_min

CONTRADICTING iff:

    current_excess_return <= proxy_contradiction_excess_max
    AND persistence <= proxy_contradiction_persistence_max

Otherwise:

    NEUTRAL

With v0.1 defaults:
- ARKG dry-run profile -> supporting;
- XBI dry-run profile -> neutral.

## 15. Output ThemeScanObservation contract

Each READY diagnostic emits exactly one ThemeScanObservation.

Fields:

    theme_id = spec.theme_id
    as_of = market_as_of
    source_type = derived_feature
    source_ref = deterministic adapter source id

    discovery_signal = None
    structure_signal = None
    breadth_signal = diagnostics.breadth_signal
    relative_strength_signal = diagnostics.relative_strength_signal
    persistence_signal = diagnostics.persistence_signal
    novelty_signal = diagnostics.novelty_signal
    volatility_signal = None

    support_direction = diagnostics.support_direction
    is_independent = true
    observed_or_inferred = inferred

source_ref format:

    market_observation:<theme_id>:<mode>:<instrument>:<market_as_of>:<input_hash_prefix>

evidence_refs includes at minimum:

    market_source_ref
    diagnostic:<diagnostic_hash>
    package:<theme_id>@<package_version>
    universe:<theme_id>@<universe_version>

Proxy observations additionally include:

    proxy:<symbol>

## 16. Batch output

MarketObservationBatch fields:

    theme_id
    cycle_as_of
    market_as_of
    observations
    diagnostics
    input_hash
    spec_hash
    config_hash

Rules:

- deterministic ordering:
  - BASKET: one source;
  - PROXY: lexical proxy symbol;
- identical semantic inputs produce identical output;
- input row ordering cannot change hashes or results;
- unrelated extra symbols do not affect the used-input hash or output.

## 17. Public API

Primary call:

    adapt_market_observations(
        package: ThemePackage,
        bars: Sequence[MarketBar],
        spec: MarketObservationSpec,
        config: MarketObservationConfig,
        cycle_as_of: str,
        market_source_ref: str,
    ) -> MarketObservationBatch

Validation:

- spec.theme_id must equal package.definition.theme_id;
- BASKET mode requires a nonempty universe;
- PROXY mode requires at least one declared proxy;
- benchmark cannot be empty;
- proxy list must not contain duplicates;
- proxy equal to benchmark is rejected;
- malformed bars raise ValueError;
- insufficient valid data returns coverage diagnostics instead of inventing values.

## 18. Effective-date semantics

Candidate effective windows remain half-open:

    effective_from <= session_date < effective_to

For full-window eligibility, the candidate must be effective across the entire requested window. Membership checks use MarketBar.session_date and the existing Candidate.is_effective semantics; they never derive membership dates from available_at.

A member with:

    effective_from = 2026-09-18

cannot contribute to a window starting 2026-09-11.

The adapter should reuse Candidate/ThemeUniverse semantics rather than invent a second membership model.

## 19. Coverage rules

### BASKET current metrics

If current eligible member count < min_basket_members:

    status = COVERAGE_PENDING
    no ThemeScanObservation is emitted

### BASKET novelty only

If current metrics are valid but stable comparison cohort is too small:

    status = READY
    current signals may emit
    novelty_signal = None
    warning records insufficient stable cohort

### PROXY

Each proxy is independent:
- valid proxy -> READY + observation;
- invalid proxy coverage -> COVERAGE_PENDING, no observation.

### Benchmark

Insufficient benchmark history makes the entire batch unable to compute windows:

    observations = ()
    one coverage diagnostic records the benchmark failure

## 20. Provenance and hashing

Hash only semantically used inputs.

The adapter first determines the required symbol set from the benchmark, declared proxies, and eligible theme members. Bars for unrelated symbols are ignored before source-level duplicate/future checks and do not affect output or hashes.

### 20.1 Source-level used-bar hash

For each basket/proxy diagnostic:

1. select only benchmark + actually used member/proxy bars;
2. normalize symbols, session_date, and available_at;
3. sort by (symbol, session_date);
4. serialize session_date, available_at, and close deterministically;
5. hash with canonical_hash.

This value is stored as MarketObservationDiagnostics.input_hash.

Unrelated extra bars must not change this hash.

### 20.2 Batch input hash

MarketObservationBatch.input_hash is:

    canonical_hash(sorted(source-level input hashes))

Thus a proxy batch with multiple proxies has one stable aggregate hash while each diagnostic retains its own exact used-input hash.

### 20.3 Config/spec hashes

    config_hash = canonical_hash(asdict(config))
    spec_hash = canonical_hash(asdict(spec))

### 20.4 Diagnostic hash

MarketObservationDiagnostics includes:

    diagnostic_hash

Compute it from the complete diagnostic object with diagnostic_hash set to None.

The resulting diagnostic reference is included in emitted observation evidence_refs.

## 21. Error handling

Raise ValueError for malformed or logically contradictory semantically used inputs:

- invalid/nonpositive/nonfinite close;
- invalid session_date or available_at;
- duplicate symbol/session_date;
- required bar available after cycle_as_of;
- theme mismatch;
- duplicate proxies;
- proxy equals benchmark;
- empty benchmark;
- invalid normalization scales <= 0;
- invalid thresholds outside documented domains.

Return COVERAGE_PENDING rather than raising for ordinary data insufficiency:

- too few benchmark sessions;
- missing member history;
- too few basket members;
- missing/incomplete proxy history.

This keeps provider/data outages separate from malformed research state.

## 22. Configuration files

### 22.1 config/adapters/market_observation_defaults.yaml

Contains exact uncalibrated normalization/support defaults from section 8.

### 22.2 config/market_observations/datacenter_infra.yaml

    version: 0.1
    theme_id: DataCenter_Infra
    mode: basket
    benchmark: SPY
    proxies: []
    current_return_sessions: 5
    prior_return_sessions: 5
    min_basket_members: 3

### 22.3 config/market_observations/genomics_bio.yaml

    version: 0.1
    theme_id: Genomics_Bio
    mode: proxy
    benchmark: SPY
    proxies: [ARKG, XBI]
    current_return_sessions: 5
    prior_return_sessions: 5
    min_basket_members: 3

These files declare research instrumentation only.

They do not alter ThemePackage permission semantics.

## 23. Acceptance fixture

Tests must not depend on live network calls.

Create pinned synthetic/public-safe close series that preserve the qualitative 2026-09-19 dry-run structure.

### DataCenter fixture

Must yield:
- enough current effective members;
- breadth < 0.25;
- current excess <= -0.02;
- BASKET support direction = CONTRADICTING;
- a READY observation;
- no member before effective_from;
- novelty computed only from stable cohort.

### Genomics fixture

Seed members have effective_from at the final/current date, so:
- forcing BASKET mode over the five-session window yields COVERAGE_PENDING;
- no retroactive basket observation is emitted.

Declared proxy fixture:
- ARKG-like proxy has excess > +0.02 and persistence >= 0.60 -> SUPPORTING;
- XBI-like proxy has positive but sub-threshold excess -> NEUTRAL;
- two diagnostics and two observations are emitted in lexical proxy order.

## 24. Testing strategy

Version 0.1 tests must prove:

1. MarketBar validates symbol/session_date/available_at/positive finite close.
2. duplicate symbol/session_date rows are rejected for used symbols.
3. required bars available after cycle_as_of are rejected.
4. session_date, not available_at, governs effective membership.
5. date-only cycle_as_of uses end-of-day UTC.
6. input ordering does not affect output.
7. extra unrelated symbols do not affect output/hash.
8. theme mismatch is rejected.
9. duplicate proxies are rejected.
10. benchmark/proxy collision is rejected.
11. insufficient benchmark history returns COVERAGE_PENDING.
12. BASKET mode excludes members admitted after window start.
13. BASKET mode respects effective_to.
14. BASKET current return is equal-weight arithmetic member return.
15. breadth is positive-member fraction.
16. persistence is fraction of daily basket-vs-benchmark wins.
17. current excess is basket return minus benchmark return.
18. stable cohort, not current cohort, drives novelty.
19. membership change is surfaced explicitly.
20. insufficient stable cohort leaves novelty missing without invalidating current signals.
21. DataCenter-style weak breadth + negative excess -> CONTRADICTING.
22. strong basket excess + broad breadth -> SUPPORTING.
23. otherwise basket direction -> NEUTRAL.
24. PROXY breadth remains None.
25. ARKG-style proxy -> SUPPORTING.
26. XBI-style modest positive proxy -> NEUTRAL.
27. negative weak proxy -> CONTRADICTING.
28. one missing proxy does not suppress another valid proxy.
29. all missing proxies emit no observations.
30. output source_type is derived_feature.
31. output is_independent is true.
32. output observed_or_inferred is inferred.
33. raw diagnostics are retained beside normalized signals.
34. per-source input hashes bind exact used bars.
35. batch input hash aggregates source-level hashes deterministically.
36. source_ref includes market_as_of and input hash prefix.
37. evidence_refs include market source, diagnostic, package, universe, and proxy when applicable.
38. scanner can consume emitted observations without special-case code.
39. Genomics effective-date fixture cannot retroactively generate a five-session member basket.
40. no ThemeRegistry/ThemeKey/Tape/router/ledger state is mutated.
41. existing full regression remains green.
42. changed-files Ruff passes.

## 25. Public repository safety

Safe to store:

- synthetic/pinned bar fixtures;
- public ticker symbols;
- public-safe uncalibrated normalization config;
- diagnostics generated from public market data;
- dry-run report.

Do not store:

- brokerage credentials;
- personal holdings;
- private sizing;
- live private decision objects;
- proprietary market-data payloads whose license forbids redistribution.

Tests should prefer synthetic/pinned transformed fixtures rather than licensed raw provider dumps.

## 26. Acceptance criteria

Increment 4 is complete when:

- MarketBar and provider-agnostic adapter interfaces exist;
- BASKET and PROXY modes work;
- effective-date look-ahead is impossible under tested contracts;
- current basket metrics and stable-cohort novelty are distinct;
- Genomics cannot retroactively create basket history;
- declared proxies can supply independent evidence;
- raw diagnostics and normalized signals are both retained;
- missing coverage fails closed;
- support direction is versioned and deterministic;
- emitted observations plug directly into Increment-3 scanner;
- no provider SDK appears in core;
- no scanner/budget/ThemeKey/Tape/router/ledger semantic change is introduced;
- all existing + new tests pass;
- changed-files Ruff passes.

## 27. Deferred work

Deliberately deferred:

- live Alpaca/Polygon/Yahoo ingestion connectors;
- volume/volatility/order-flow signals;
- dynamic proxy discovery;
- proxy-weight learning;
- layer-weighted or exposure-weighted baskets;
- survivorship-bias historical universe reconstruction;
- calibrated normalization scales;
- learned support-direction classifier;
- scheduled market-data refresh;
- portfolio sizing/execution.

Those should only be added after the provider-neutral adapter has accumulated replayable diagnostics and outcome evidence.


## 28. Validation domains

Configuration validation is explicit:

- current_return_sessions >= 1;
- prior_return_sessions >= 1;
- min_basket_members >= 1;
- relative_strength_scale > 0;
- novelty_scale > 0;
- breadth and persistence thresholds must lie in [0,1];
- excess-return thresholds must be finite;
- support thresholds must not make SUPPORTING and CONTRADICTING overlap under the same mode.

MarketObservationStatus enum names are READY and COVERAGE_PENDING with serialized values ready and coverage_pending.

MarketObservationMode enum names are BASKET and PROXY with serialized values basket and proxy.

MarketObservationBatch.market_as_of is optional because a completely missing benchmark can fail before any market session is established.
