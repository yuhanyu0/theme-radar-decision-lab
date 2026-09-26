# Repricing Graph v0.1 — ETN / DataCenter shadow slice

This directory is an **experimental, shadow-only** vertical slice. It does not create orders, size capital, or modify the production decision API.

## Fixed scope

- Theme: `DataCenter_Infra`
- Layer: `electrical_switchgear`
- Initial target: `ETN`
- Fundamental variable: `ETN_FY2026_ADJUSTED_EPS`
- Catalyst class: next earnings / guidance update
- Evaluation horizons: 20 and 60 trading days

The mechanism under test is **Causal Repricing Lag**: a documented world/theme change must transmit through an evidence-backed company exposure into a fundamental implication that differs from a point-in-time market expectation and has a bounded reveal catalyst.

Theme strength, Scanner priority, Readiness, linkage, Tape, and Playbook scores are not alpha estimates. Linkage is diagnostic; Tape is price-assimilation context.

## Current case

`cases/ETN_2026Q2_shadow.yaml` is frozen using information available by its declared as-of. It deliberately does not invent a positive gap: Eaton's FY2026 adjusted-EPS guidance interval contains the public consensus snapshot used by the case, so the current case remains `RESEARCHING`.

## Outcome protocol

The frozen case never contains future outcomes. After 20 and 60 future sessions exist, `evaluate_shadow_case` may append an external `ShadowOutcomeRecord` using the existing `decision_lab.outcomes.evaluate_forward_outcomes` machinery. Evaluation cannot mutate the frozen case or its hash.

A single case cannot establish alpha and no p-value is produced.

## Required ablations

- FULL
- NO_ECONOMIC_EXPOSURE_VALIDATION
- NO_MARKET_EXPECTATION_GAP
- NO_CATALYST_REQUIREMENT
- NO_TAPE_CONTEXT
- NO_TARGET_EXCLUDED_CONTROL

If a later locked cohort shows no incremental information from the expectation-gap component, the central architecture triggers its kill criterion. The response is to stop or redesign the mechanism, not to add more technical signals.

## Expansion gate

Do not expand to a multi-company cohort until this one case survives PIT/provenance review and its future outcome can be appended without hindsight. No historical alpha claim is permitted from the current case.
