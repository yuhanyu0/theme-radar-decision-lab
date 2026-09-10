# Theme Radar Decision Lab

An independent, auditable research/evaluation layer for Theme Radar.

## Design principle

`theme-radar-log` is treated as **model output**, not ground truth. This repository keeps independent evidence, dynamic theme universes, expression/linkage diagnostics, Tape state, playbook routing, immutable decisions, and walk-forward outcomes separate.

Pipeline:

`Raw Evidence -> Radar/Navigator Snapshot -> Dynamic Universe -> Company/Expression Validation -> Tape State Machine -> Playbook Router -> Immutable Decision Ledger -> Outcome Engine -> Walk-forward Evaluation`

## Non-negotiable invariants

1. **No circular proof**: Radar output cannot be used as its own ground truth.
2. **No circular theme controls**: ticker linkage uses leave-one-out controls.
3. **No falling-knife C-play**: mispricing requires stabilization before becoming executable.
4. **Live decisions are append-only**: newer model versions may recompute into `recomputed/`, never overwrite `ledger/live/`.
5. **Observed facts, model inference, and action are separate fields.**
6. **No automatic brokerage execution.** This is a research and evaluation system.

## MVP scope

The first pilot is `DataCenter_Infra`, because it requires a dynamic value-chain universe rather than a fixed expression list. The engine is designed to support layers such as power/time-to-power, grid/interconnection, electrical/switchgear, thermal/liquid cooling, EPC/MEP, networking/interconnect/optics, compute-support hardware, and data-center ownership.

## Repository layout

```text
src/decision_lab/          core Python package
config/                    versioned public-safe configuration templates
schemas/                   JSON schemas for evidence/decisions/outcomes
ledger/live/               immutable live decisions (enable only in a private repo)
recomputed/                later-model replays; never mixed with live decisions
outcomes/                   forward outcome records
reports/                    generated evaluation summaries
scripts/                    runnable entry points
tests/                      invariant/unit tests
.github/workflows/          CI; scheduled live jobs should only be enabled after privacy review
```

## Repository privacy

This repository was detected as **public** at bootstrap time. The initial bootstrap intentionally contains only a public-safe scaffold and no personal holdings, private research notes, live Decision Ledger entries, secrets, or proprietary threshold configuration. Before enabling live decision logging, cross-repository Radar ingestion, or scheduled research artifacts, change the repository to private and configure required secrets in GitHub Actions.

## Next milestones

- v0.1: schemas + dynamic universe interfaces + leave-one-out linkage diagnostics + Tape path state machine + A-H router interfaces.
- v0.2: DataCenter independent market-data pipeline and theme sub-controls.
- v0.3: immutable Decision Ledger + forward 1/3/5/10/20D outcomes + MAE/MFE/missed-upside metrics.
- v0.4: scheduled walk-forward evaluation and probability calibration.
