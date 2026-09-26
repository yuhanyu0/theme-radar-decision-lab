# ETN Repricing Graph — Native shadow slice

This is experimental software, not a profitable strategy or live-trading system.
The reusable types, gap arithmetic, PIT input checks, original linkage/Tape
adapters, frozen compiler and diagnostic outcome interfaces are implemented.
See `NATIVE_STATUS.md` for recovery history and remaining model/data work.

## Current real snapshot

Use `cases/ETN_20260926_capture.yaml`. It has **no independent EPS forecast**.
Company guidance is a weaker comparison anchor, not the market's beliefs.
The vendor consensus excerpt is not current-vintage verified and is excluded
from candidate promotion. The expected earnings window is not issuer-confirmed.
The output therefore stays `RESEARCHING`, with no position size or expected stock
return. The earlier `ETN_2026Q2_shadow.yaml` is a quarantined development fixture.

The runner uses captured real prices for ETN, POWL, NVT, SPY and XLI. POWL and
NVT are the current same-layer, target-excluded peers from the existing universe.
They are not a replacement for the entire DataCenter Theme observation.
Statistical linkage and Tape cannot establish economic causality or alpha.

## Reproduce with captured inputs

From the repository root, using Python 3.11+ and existing project dependencies:

```bash
PYTHONPATH=src:. pytest -q
PYTHONPATH=src:. pytest -q experiments/repricing_graph_v0_1/test_*.py
PYTHONPATH=src:. python -m experiments.repricing_graph_v0_1.run_shadow \
  --market-dir /path/to/captured/market \
  --output /path/to/new/shadow_report.json
```

The market directory must contain `receipt.json` and all five hash-matching CSVs.
No network or broker call occurs inside the compiler/runner. The output path is
exclusive-create: a previous frozen report cannot be silently overwritten.
Runtime sources and inputs are preserved in the delivered offline bundle.

## What is and is not tested

A connected supported graph path, positive expectation gap and complete input
bindings are software prerequisites for a synthetic CANDIDATE. Such a label is
not proof that the stated causal model or source interpretation is true.

The real case does not meet those economic prerequisites. Tasks concerning an
independent company forecast and calibrated return scenarios remain outstanding.
The source/catalyst rows, valuation assumptions, graph, context and estimates are
all retained in canonical frozen inputs so meaningful changes change the hash.

20/60-session outputs use existing close-to-close diagnostic outcomes. They are
not next-open executable returns, net-of-cost P&L or an investment recommendation.
Ablations are metadata only at this stage, not evidence of predictive contribution.
Main, production API, portfolio sizing and broker execution remain unchanged.
