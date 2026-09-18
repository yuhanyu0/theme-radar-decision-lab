# ThemeKey Calibration State — Fail-Closed Design

Date: 2026-09-18  
Status: approved in chat; implementation not started  
Repository: `theme-radar-decision-lab`  
Branch: `feature/genomics-bio-theme-package`

## 1. Context

Increment 2 onboarded `Genomics_Bio` as the first materially different non-DataCenter theme. The package and biotech evidence adapter passed the existing generic package, universe, Tape, router, and regression contracts without requiring theme-specific execution logic.

The pressure test exposed one genuine generic-core defect: a newly created `ThemeKeyPolicy` with all optional thresholds unset can evaluate as satisfied because there is no explicit representation of policy calibration readiness.

A temporary Genomics configuration used `structure_percentile_min: 0.80` only to keep permission closed. That value is not empirically calibrated for Genomics and must not be retained as a pseudo-threshold.

## 2. Goal

Make Theme-key permission fail closed until a theme has an explicit, reviewable calibration state and valid gating conditions.

The engine must distinguish:

- a theme that has merely been discovered and researched;
- a theme whose Theme-key policy is operational but provisional;
- a theme whose policy has been validated against historical/forward evidence.

Discovery strength, Radar migration, candidate quality, or Tape quality must never implicitly promote an uncalibrated theme into actionable permission.

## 3. Non-goals

This correction does not:

- calibrate Genomics thresholds;
- claim that DataCenter thresholds are validated;
- change Tape states or A-H playbook semantics;
- change candidate membership states;
- add portfolio sizing or brokerage execution;
- create a second permission engine beside `ThemeKeyPolicy`;
- rewrite historical Decision Objects.

## 4. Selected design

Introduce a `ThemeCalibrationState` enum:

```text
uncalibrated
operational
validated
```

Meaning:

### `uncalibrated`

The theme may be discovered, researched, ranked, and monitored.

Theme-key evaluation is always fail-closed:

```text
satisfied = false
max permission = research/watch only
reason includes "theme key policy uncalibrated"
```

No synthetic sentinel threshold is required.

### `operational`

The theme has an explicit provisional policy approved for monitoring decisions, but the policy has not yet earned validated status from outcome evidence.

The configured gates may be evaluated normally.

DataCenter_Infra is initially `operational`.

### `validated`

The theme policy has been evaluated against sufficient immutable historical and/or forward outcome evidence under a documented calibration protocol.

Configured gates may be evaluated normally.

No current theme is automatically promoted to `validated` by this change.

## 5. ThemeKeyPolicy contract

Extend `ThemeKeyPolicy` with:

```text
calibration_state: ThemeCalibrationState = uncalibrated
```

Existing fields remain compatible:

```text
minimum_flow
probe_structure
full_structure
structure_percentile_min
minimum_valid_sessions
minimum_carry
max_raw_calibrated_gap
```

### Evaluation order

`ThemeKeyPolicy.evaluate(...)` must execute in this order:

1. If `calibration_state == uncalibrated`, return fail-closed immediately.
2. Validate that an operational/validated policy has at least one substantive evidence gate configured.
3. Apply minimum valid-session requirements.
4. Apply configured flow / structure / structure-percentile / carry / raw-vs-calibrated consistency gates.
5. Return satisfied only if every configured requirement passes.

A substantive evidence gate is any non-null item among:

```text
minimum_flow
probe_structure or full_structure for the requested permission
structure_percentile_min
minimum_carry
max_raw_calibrated_gap
```

`minimum_valid_sessions` alone is not sufficient to make a policy operational.

If an operational/validated policy has no substantive evidence gate for the requested permission, evaluation must fail closed with an explicit configuration reason rather than silently pass.

## 6. ThemeKeyEvaluation output

Keep the current shape compatible:

```text
ThemeKeyEvaluation
  satisfied
  permission
  reasons
```

No new output field is required in this increment. The calibration state is already bound to the policy/config version used to produce the evaluation.

Required reasons include:

```text
theme key policy uncalibrated
theme key policy has no substantive evidence gate
insufficient valid sessions
flow condition not satisfied
structure condition not satisfied
structure percentile condition not satisfied
carry condition not satisfied
raw/calibrated inconsistency exceeds policy
```

The first applicable fail-closed reason should be preserved; downstream code must not reinterpret missing calibration as ordinary threshold failure.

## 7. Configuration semantics

### Global defaults

`config/policies/theme_key_defaults.yaml` becomes explicitly:

```yaml
calibration_state: uncalibrated
```

All existing threshold defaults remain null.

### DataCenter_Infra

`config/themes/datacenter_infra.yaml` becomes explicitly:

```yaml
theme_key_policy:
  calibration_state: operational
  minimum_flow: 0.50
  probe_structure: 0.08
  full_structure: 0.35
  minimum_valid_sessions: 2
```

This preserves current semantics without claiming validation.

### Genomics_Bio

`config/themes/genomics_bio.yaml` becomes explicitly:

```yaml
theme_key_policy:
  calibration_state: uncalibrated
  minimum_valid_sessions: 3
```

The temporary `structure_percentile_min: 0.80` is removed.

Genomics may continue through discovery, company research, hierarchical linkage, Tape, and playbook routing, but Theme-key permission remains closed until a separate calibration task promotes its policy.

## 8. Backward compatibility

The correction should be compatible with the current engine except for one intentional safety change:

- a `ThemeKeyPolicy()` with no explicit calibration state now fails closed;
- older code that relied on an empty policy evaluating true is considered unsafe behavior and is intentionally not preserved.

No changes are required to:

- `ThemeUniverse`;
- candidate effective-date logic;
- hierarchical linkage;
- Tape assessment;
- A-H router;
- immutable ledger schema.

## 9. TDD requirements

Implementation must follow this red-green sequence:

1. Add a test proving default/uncalibrated policy cannot satisfy Theme key.
2. Add a test proving an operational policy with no substantive evidence gate fails closed.
3. Add a test proving the existing DataCenter operational policy still evaluates as before when its configured gates pass/fail.
4. Add a package test proving Genomics is uncalibrated and contains no invented `0.80` structure threshold.
5. Only then modify core policy/configuration.
6. Run the complete existing test suite.
7. Run changed-files Ruff on all touched Python/tests.

## 10. Acceptance criteria

This correction is complete when:

- `ThemeCalibrationState` exists with `uncalibrated / operational / validated`;
- global ThemeKey policy defaults to `uncalibrated`;
- uncalibrated evaluation always returns `satisfied=false`;
- operational/validated policies with no substantive evidence gate fail closed;
- DataCenter is explicitly `operational` with its existing thresholds unchanged;
- Genomics is explicitly `uncalibrated`;
- the temporary Genomics `structure_percentile_min=0.80` is removed;
- no Tape/A-H behavior changes;
- no live decision logging is enabled;
- full pytest passes;
- changed-files Ruff passes.

## 11. Deferred work

A later calibration task will define how a theme moves:

```text
uncalibrated -> operational -> validated
```

That task must specify evidence/history requirements, outcome metrics, walk-forward validation, and demotion rules. This correction only creates safe state semantics; it does not invent calibration evidence.
