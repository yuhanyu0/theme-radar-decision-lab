# Native implementation / qualification status

Production baseline: `c5866ad8f09a472cf631a764f911547c05d337d9`.
Resume point: PR15 `c8e483d4e06ea72dabe8caf1f90681242657517c`.
Execution method: Native. The older PR14 branch is left untouched.

Tasks 1–7 implementation was recovered from existing Git history, not re-created or
claimed as entirely new work in this resumed turn. The recovered suite had six
failing semantic checks and 49 passing checks; original 452 tests passed.

Repairs and their new/recovered RED tests cover source/catalyst content preservation,
estimate/source/case chronology, row-level future-market rejection, forged gap and
cross-target context rejection, connected supported causal paths, nonpositive-gap
rejection, full frozen input retention, numeric/scenario validity and mismatched
outcome calendars. A real-data run exposed a NumPy boolean transport failure not
present in the fixtures: a reproducer was added before scalar normalization at the
experimental JSON boundary. Native Tape and production files are unchanged.

## Real case and boundaries

`cases/ETN_20260926_capture.yaml` is the current source capture. Its information
cutoff is September 26, 2026 07:20:20 UTC; the record is created after capture, not
backdated into a September 25 trading recommendation. Five Yahoo symbol files
were acquired through the existing yfinance dependency in read-only GitHub CI.
They are current-vintage history for current context, not historical PIT data.

`cases/ETN_2026Q2_shadow.yaml` is retained as a **development fixture only**.
Its earlier secondary-source and calendar timestamps were not reproducibly
verified in this resumption; it is not the real current shadow record.

Primary management guidance is 13.40–13.60 USD/share for FY2026 adjusted EPS.
It is stored as COMPANY_GUIDANCE, never as our independently derived forecast.
The 13.56 vendor estimate was visible in a search-index excerpt, while the direct
page returned a JavaScript challenge; exact source vintage and metric
comparability are unverified. It is retained only as a diagnostic reference,
not as a fresh consensus input. An earnings-window estimate is explicitly
unconfirmed. No fabricated confidence, elasticity, EPS forecast, return scenario,
position or trade is produced.

The real output must be RESEARCHING. The outstanding business work is an actual
source-supported transmission-to-EPS model and a fresh, comparable expectation
reference. A code-green result does not close these model/data gaps.

## Evaluation scope

Native close-to-close outcomes are future diagnostics, not executable entry
returns after costs. 20d and 60d remain null until sufficient later sessions
exist. Ablation records are declarations of omitted inputs; no ablation
performance experiment or alpha test was run. One case cannot establish alpha
or kill the architecture from equal diagnostic metrics.

All validation is self-review plus executable tests, not independent peer review.
Do not merge this experimental branch into main as part of this task.
