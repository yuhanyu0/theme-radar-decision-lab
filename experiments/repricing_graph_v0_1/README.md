# Repricing Graph v0.1 — ETN/DataCenter shadow slice

This directory is an **experimental shadow-decision vertical slice**. It is not a
production `decision_lab` API, a portfolio strategy, or a live-trading system.

## Scope

- Theme: `DataCenter_Infra`
- Layer: `electrical_switchgear`
- Initial target: `ETN`
- Primary variable: `ETN_FY2026_ADJUSTED_EPS`
- Current real case: `cases/ETN_2026Q2_shadow.yaml`
- Frozen evaluation horizons: 20 and 60 trading sessions after the case

The real case is intentionally `RESEARCHING`: company FY2026 adjusted EPS guidance
($13.40-$13.60) overlaps the observed Sep. 25 sell-side consensus ($13.55 average).
Strong electrical demand by itself is therefore not treated as alpha.

## What existing components mean here

- Theme / Market Observation: repricing-diffusion context, not alpha.
- Scanner: research candidate selection, not alpha.
- target-excluded linkage: statistical diagnostic, not causal proof.
- Tape: price-assimilation / entry context, not thesis generation.
- Readiness: research-integrity gate, not expected return.

## Outcome protocol

The frozen case never contains future returns. Once enough future sessions exist,
`evaluate_shadow_case` appends separate 20d/60d outcomes using the existing
`decision_lab.outcomes.evaluate_forward_outcomes` implementation.

Results may be compared with:
- SPY;
- a relevant sector benchmark;
- a target-excluded Theme control.

One shadow case cannot establish alpha or support a p-value.

## Kill rule

The first cohort must include the frozen ablations in `evaluate.Ablation`.
If removing `NO_MARKET_EXPECTATION_GAP` does not degrade later locked-sample
performance, the central Repricing Graph thesis fails. Do not compensate by adding
more indicators or post-hoc thresholds.

## Explicit non-goals

No BUY/SELL output, no capital sizing, no broker integration, no historical
backfill of the 2026 Theme universe, no generalized graph authoring, and no claim
that the present ETN shadow case is an investment recommendation.
