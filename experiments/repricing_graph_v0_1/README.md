# Repricing Graph v0.1 — ETN Shadow Slice

This directory is an **experimental, shadow-only** implementation of the approved Repricing Graph design.

## Scope

- Theme: `DataCenter_Infra`
- Layer: `electrical_switchgear`
- Target: `ETN`
- Primary fundamental variable: `ETN_FY2026_ADJUSTED_EPS`
- Catalyst class: next earnings / guidance update
- Evaluation horizons: 20 and 60 trading sessions

It does **not** place orders, size live capital, or modify the production decision stack.

## What this experiment is testing

The mechanism under test is Causal Repricing Lag:

1. a real-world Theme variable changes;
2. the change has an evidence-backed causal path to ETN fundamentals;
3. related market prices may begin repricing;
4. the target's market expectation may differ from the system's fundamental implication;
5. a bounded catalyst can reveal the disputed variable.

Theme state, Scanner priority, linkage, Tape, and Playbook outputs are context or diagnostics. None of them is an alpha estimate by itself.

## Frozen first case

The current shadow case is:

`cases/ETN_2026Q2_shadow.yaml`

Case as-of:

`2026-09-25T20:00:00+00:00`

The frozen FY2026 inputs are deliberately not bullish:

- management adjusted EPS guidance: **$13.40-$13.60**
- point-in-time reported sell-side consensus: **$13.56**

The resulting expectation-gap interval crosses zero. That result is retained intentionally. The architecture is being tested; the case is not altered to manufacture a trade.

`CANDIDATE` in this experiment means the mechanism object is sufficiently complete to freeze and shadow-track. It does **not** mean BUY, SELL, POSITIONABLE, or live execution permission.

## Point-in-time contract

Every frozen source records:

- `event_time`
- `available_at`
- source URL / provenance
- variable and value/range
- period and unit
- revision lineage
- direct vs inferred status

The loader rejects future-dated evidence, hidden future outcomes, mislabeled consensus, catalyst hindsight, and Theme membership before its effective period.

Runtime code does not fetch the web.

## Context reuse

The slice reuses existing:

- `leave_one_out_control`
- `rolling_linkage`
- `assess_tape_state`
- `evaluate_forward_outcomes`

Linkage does not prove causal exposure. Tape does not generate direction. Missing Theme market observation becomes an explicit warning rather than a fabricated score.

## Outcome append

The original shadow decision is immutable.

After enough sessions have elapsed, call `evaluate_shadow_case` with immutable historical price series. It appends evaluation records for:

- ABSOLUTE
- SPY
- sector benchmark
- target-excluded Theme control

at 20d and 60d where enough future observations exist.

The evaluator records return, MFE, MAE, and benchmark-relative outcomes through the existing `decision_lab.outcomes` implementation. It never feeds those future outcomes back into the original case hash.

A single case must not produce a p-value, alpha estimate, or portfolio-performance claim.

## Ablations

The frozen ablation set is:

- `FULL`
- `NO_ECONOMIC_EXPOSURE_VALIDATION`
- `NO_MARKET_EXPECTATION_GAP`
- `NO_CATALYST_REQUIREMENT`
- `NO_TAPE_CONTEXT`
- `NO_TARGET_EXCLUDED_CONTROL`

The central architecture fails if removing the market-expectation-gap component leaves the mechanism's later performance unchanged in an adequately sized locked cohort.

This v0.1 only creates provenance-preserving ablation records. It does not pretend one shadow case can estimate component effects.

## Kill criteria

Do not expand this system by adding more signals if any of the following is ultimately true:

1. expectation-gap cases do not outperform matched simpler baselines after realistic costs;
2. the expectation-gap component adds no incremental information;
3. economic exposure cannot be made point-in-time and evidence-backed;
4. market expectations cannot be reconstructed without hindsight;
5. target-excluded Theme repricing adds no information beyond target momentum;
6. catalyst requirements merely select past winners rather than improve prospective timing;
7. results are concentrated in one company or overlapping event cluster;
8. modest cost / timing perturbations erase the result;
9. the mechanism requires repeated post-hoc threshold tuning;
10. outcome attribution cannot distinguish model failure from execution noise.

## ALPHA-0 relationship

The earlier generic ETF ALPHA-0 remains a **generic price baseline / negative control**.

Its MOM63 / RS20 / ACCEL20 / VOLX tests are not tests of this Theme / Repricing Graph mechanism and must not be cited as evidence for or against it.

## What engineering success means

Engineering success for this slice means:

> one auditable ETN shadow Repricing Case can be frozen from point-in-time inputs and later evaluated without hindsight.

It does **not** mean the strategy has alpha.
