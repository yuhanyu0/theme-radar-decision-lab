# World Scanner Real-Data Dry Run — 2026-09-19

Status: diagnostic dry run; not a trade decision  
Market data cutoff: 2026-09-18 close (2026-09-19 is Saturday)  
Radar snapshot: theme-radar-log commit 1de14bee17e0f8d297b9d822f3f57f279f670977  
Scanner/budget engine: main after PR #3 merge, commit bfd27f84f68f91b63527e02f9a621e8c361f9de8

## Purpose

Test the newly merged World Scanner + Research Budget Funnel with real 2026-09-19 discovery inputs and independent market evidence.

This dry run is intentionally narrow:

- registered themes: DataCenter_Infra, Genomics_Bio;
- model-only discovery candidates: MegaCap_AI, Space, Sector_Fin, Rates;
- no company deep research;
- no Tape refresh;
- no ThemeKey permission changes;
- no live ledger write;
- no brokerage action.

The goal is to test research routing, not investment selection.

## Radar/model input

Latest 2026-09-19 Theme Radar brief:

- v1 leader: Nuclear_Uranium;
- v2 leader: Rates;
- v2/v3 include Genomics_Bio;
- top migration risers begin with DataCenter_Infra, Genomics_Bio, MegaCap_AI, Space, Sector_Fin;
- watchlist: DataCenter_Infra, Genomics_Bio, MegaCap_AI, Space, Sector_Fin + Rates.

Radar remains model output only.

For this dry run, watchlist rank was translated into provisional model-only discovery/novelty diagnostics. These normalizations are diagnostic and uncalibrated; they are not persisted production rules.

## Independent market evidence

### DataCenter_Infra

Active public seed basket: 22 members.

Window:
- current 5-session window: 2026-09-11 close -> 2026-09-18 close;
- prior comparison window: 2026-09-03 close -> 2026-09-11 close.

Observed:
- positive-member breadth: 13.6%;
- equal-weight 5-session basket return: -2.53%;
- SPY 5-session return: -0.33%;
- excess return vs SPY: -2.20 percentage points;
- daily basket-vs-SPY outperformance frequency: 4/5 sessions = 0.80;
- prior-window excess return: +4.51 percentage points;
- absolute change in excess return between windows: 6.71 percentage points.

Diagnostic interpretation:
- current cross-sectional breadth is very weak;
- relative performance flipped from strongly positive to negative;
- daily persistence is mixed with the aggregate reversal rather than cleanly confirming it.

For the dry run this source was classified as an independent contradiction because:
- current 5-session excess return < -2 percentage points; and
- positive-member breadth < 25%.

That contradiction is a review trigger, not a sell signal.

### Genomics_Bio

The seed universe only became effective on 2026-09-18, so using its members retrospectively for a multi-day historical basket would violate the effective-date invariant.

Therefore the dry run used two independent public market proxies instead of retroactively backfilling the new seed:

ARKG:
- 5-session return: +13.44%;
- excess return vs SPY: +13.77 percentage points;
- outperformed SPY on 5/5 sessions;
- prior-window excess: -2.41 percentage points;
- excess-return change: 16.18 percentage points.

XBI:
- 5-session return: +0.28%;
- excess return vs SPY: +0.61 percentage points;
- outperformed SPY on 3/5 sessions;
- prior-window excess: -3.83 percentage points;
- excess-return change: 4.43 percentage points.

Diagnostic interpretation:
- genomics-specific proxy strength is large in ARKG;
- broad biotech confirmation is positive but much weaker in XBI;
- this is corroboration with substantial internal dispersion, not uniform sector strength.

## Provisional normalization used only for this dry run

To exercise the current v0.1 scanner contract without adding production code:

- breadth_signal = positive-member fraction;
- relative_strength_signal = clip(0.5 + five_session_excess_return / 0.20, 0, 1);
- persistence_signal = fraction of last five sessions outperforming the benchmark;
- novelty_signal = clip(abs(current_window_excess - prior_window_excess) / 0.10, 0, 1);
- model discovery/novelty values were rank-based watchlist diagnostics;
- DataCenter independent support direction = contradicting under the -2pp / 25% rule above;
- ARKG = supporting;
- XBI = neutral.

These mappings are explicitly uncalibrated. Their purpose is to pressure-test the routing architecture and identify what should become a versioned adapter.

## Scanner replay

Approximate v0.1 scanner outputs under the current formula:

| Theme | Discovery | Persistence | Breadth | Relative strength | Novelty | Evidence confidence | Independent support | Contradiction | Research priority | Forced review |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| DataCenter_Infra | 0.90 | 0.80 | 0.14 | 0.39 | 0.75 | 0.44 | 0 | 1 | 0.36 | yes |
| Genomics_Bio | 0.85 | 0.80 | n/a | 0.77 | 0.73 | 0.94 | 1 | 0 | 0.82 | no |
| MegaCap_AI | 0.80 | n/a | n/a | n/a | 0.65 | 0.00 | 0 | 0 | 0.48 | no |
| Space | 0.75 | n/a | n/a | n/a | 0.55 | 0.00 | 0 | 0 | 0.43 | no |
| Sector_Fin | 0.70 | n/a | n/a | n/a | 0.50 | 0.00 | 0 | 0 | 0.40 | no |
| Rates | 0.65 | n/a | n/a | n/a | 0.60 | 0.00 | 0 | 0 | 0.42 | no |

## Budget allocation replay

With current v0.1 capacity:
- theme_research_slots = 8;
- full_decision_slots = 3;
- minimum_independent_sources = 1;
- confidence_floor = 0.45;
- full_priority_gate = 0.65;
- full_novelty_gate = 0.35.

Result:

| Theme | Allocation | Why |
|---|---|---|
| DataCenter_Infra | FULL_DECISION_RESEARCH | forced review from independent contradiction; this is risk/reassessment, not positive opportunity |
| Genomics_Bio | FULL_DECISION_RESEARCH | registered strengthening theme, independent corroboration, confidence/priority/novelty gates pass |
| MegaCap_AI | SCAN_ONLY | model-only and unregistered |
| Space | SCAN_ONLY | model-only and unregistered |
| Sector_Fin | SCAN_ONLY | model-only and unregistered |
| Rates | SCAN_ONLY | model-only and unregistered |

Genomics_Bio remains ThemeKey-uncalibrated even if routed to FULL_DECISION_RESEARCH. Research allocation does not create action permission.

## What this dry run established

The routing architecture produced the intended qualitative separation:

1. model-only Radar strength did not become expensive research for unknown themes;
2. Genomics could earn deep research from independent evidence while remaining action-permission closed;
3. DataCenter deterioration did not simply disappear from the queue — independent contradiction forced a full review;
4. effective-date discipline prevented retroactive use of the newly created Genomics seed basket.

## Main gap exposed

The current engine starts at ThemeScanObservation.

There is not yet a canonical, versioned transformation:

    raw market bars + effective-dated theme membership + benchmark/proxy definition
        -> breadth / relative strength / persistence / novelty
        -> support_direction
        -> ThemeScanObservation

This dry run had to construct that transformation manually.

That is now the highest-value next engineering step.

## Recommended Increment 4

Build a provider-agnostic MarketObservationAdapter that:

- consumes raw timestamped bars and current ThemePackage/effective membership;
- never includes a member before effective_from;
- supports target theme baskets and declared external proxies;
- emits one or more ThemeScanObservation records with full provenance;
- keeps raw derived statistics alongside normalized scanner signals;
- uses versioned uncalibrated normalization config;
- never touches ThemeRegistry mutation, ThemeKey, Tape, router, ledger, or brokerage execution.

The first acceptance fixture should reproduce the qualitative 2026-09-19 dry-run separation above from pinned synthetic/public-safe bars, not from live network calls.
