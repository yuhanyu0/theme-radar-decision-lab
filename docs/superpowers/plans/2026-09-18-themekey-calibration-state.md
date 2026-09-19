# ThemeKey Calibration State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit Theme-key calibration readiness so uncalibrated themes fail closed, while preserving existing DataCenter operational thresholds and removing the invented Genomics percentile sentinel.

**Architecture:** Extend the existing `ThemeKeyPolicy` with a small calibration-state enum and keep all permission logic in the same policy object. Configuration declares whether a theme is `uncalibrated`, `operational`, or `validated`; uncalibrated policies and operational/validated policies without a substantive evidence gate return explicit fail-closed reasons. No Tape, A-H router, linkage, universe, or ledger interface changes.

**Tech Stack:** Python 3.11, dataclasses, Enum, PyYAML, pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-18-themekey-calibration-state-design.md`

## Global Constraints

- Calibration states are exactly `uncalibrated`, `operational`, and `validated`.
- Global/default Theme-key policy is `uncalibrated`.
- `uncalibrated` must always return `satisfied=False`.
- `operational` or `validated` with no substantive evidence gate for the requested permission must fail closed.
- `minimum_valid_sessions` alone is not a substantive evidence gate.
- DataCenter remains `operational` with `minimum_flow=0.50`, `probe_structure=0.08`, `full_structure=0.35`, and `minimum_valid_sessions=2`.
- Genomics remains `uncalibrated`; remove the temporary `structure_percentile_min=0.80`.
- No changes to Tape states, A-H router semantics, hierarchical linkage, candidate membership, or ledger schema.
- No live decision logging or brokerage execution.

---

## File map

- Modify `src/decision_lab/themes.py`: define `ThemeCalibrationState`, add it to `ThemeKeyPolicy`, and implement fail-closed evaluation order.
- Modify `src/decision_lab/__init__.py`: export `ThemeCalibrationState`.
- Modify `tests/test_themes.py`: core policy RED/GREEN tests.
- Modify `tests/test_genomics_bio_package.py`: Genomics package calibration contract.
- Modify `tests/test_theme_package_compat.py`: DataCenter operational compatibility contract.
- Modify `config/policies/theme_key_defaults.yaml`: explicit uncalibrated default.
- Modify `config/themes/datacenter_infra.yaml`: explicit operational state; thresholds unchanged.
- Modify `config/themes/genomics_bio.yaml`: explicit uncalibrated state; remove invented percentile.
- Optional temporary CI audit file only if needed for changed-files Ruff; remove it before final branch state.

---

### Task 1: Add fail-closed calibration semantics to ThemeKeyPolicy

**Files:**
- Modify: `tests/test_themes.py`
- Modify: `src/decision_lab/themes.py`
- Modify: `src/decision_lab/__init__.py`

**Interfaces:**
- Consumes: existing `ThemeKeyPolicy.evaluate(...)` and `ThemeKeyEvaluation`.
- Produces:
  - `ThemeCalibrationState(str, Enum)`
  - `ThemeKeyPolicy.calibration_state: ThemeCalibrationState`
  - unchanged `ThemeKeyEvaluation(satisfied, permission, reasons)`

- [ ] **Step 1: Write the failing calibration-state tests**

Add to `tests/test_themes.py`:

```python
from decision_lab.themes import (
    ThemeCalibrationState,
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemeLifecycleState,
    ThemeRegistry,
)


def test_default_theme_key_policy_is_uncalibrated_and_fails_closed():
    policy = ThemeKeyPolicy()

    result = policy.evaluate(
        flow=1.0,
        structure=1.0,
        valid_sessions=999,
        permission="probe",
        structure_percentile=1.0,
        carry=1.0,
        raw_calibrated_gap=0.0,
    )

    assert policy.calibration_state is ThemeCalibrationState.UNCALIBRATED
    assert not result.satisfied
    assert result.reasons == ("theme key policy uncalibrated",)


def test_operational_policy_without_substantive_gate_fails_closed():
    policy = ThemeKeyPolicy(
        calibration_state=ThemeCalibrationState.OPERATIONAL,
        minimum_valid_sessions=2,
    )

    result = policy.evaluate(
        flow=None,
        structure=None,
        valid_sessions=10,
        permission="probe",
    )

    assert not result.satisfied
    assert result.reasons == ("theme key policy has no substantive evidence gate",)


def test_operational_policy_evaluates_configured_gates_normally():
    policy = ThemeKeyPolicy(
        calibration_state=ThemeCalibrationState.OPERATIONAL,
        minimum_flow=0.50,
        probe_structure=0.08,
        full_structure=0.35,
        minimum_valid_sessions=2,
    )

    assert policy.evaluate(
        flow=0.52,
        structure=0.10,
        valid_sessions=2,
        permission="probe",
    ).satisfied
    assert not policy.evaluate(
        flow=0.49,
        structure=0.10,
        valid_sessions=2,
        permission="probe",
    ).satisfied
    assert policy.evaluate(
        flow=0.52,
        structure=0.36,
        valid_sessions=2,
        permission="full",
    ).satisfied
```

Update the older global-default test so it asserts the new fail-closed state rather than only checking null thresholds.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
pytest -q tests/test_themes.py
```

Expected: collection or assertion failure because `ThemeCalibrationState` and `ThemeKeyPolicy.calibration_state` do not yet exist.

- [ ] **Step 3: Implement the minimal enum and fail-closed evaluation order**

In `src/decision_lab/themes.py`, add:

```python
class ThemeCalibrationState(str, Enum):
    UNCALIBRATED = "uncalibrated"
    OPERATIONAL = "operational"
    VALIDATED = "validated"
```

Extend `ThemeKeyPolicy`:

```python
@dataclass(frozen=True)
class ThemeKeyPolicy:
    calibration_state: ThemeCalibrationState = ThemeCalibrationState.UNCALIBRATED
    minimum_flow: float | None = None
    probe_structure: float | None = None
    full_structure: float | None = None
    structure_percentile_min: float | None = None
    minimum_valid_sessions: int = 1
    minimum_carry: float | None = None
    max_raw_calibrated_gap: float | None = None
```

At the start of `evaluate(...)`:

```python
if self.calibration_state is ThemeCalibrationState.UNCALIBRATED:
    return ThemeKeyEvaluation(
        satisfied=False,
        permission=permission,
        reasons=("theme key policy uncalibrated",),
    )

required_structure = self.full_structure if permission == "full" else self.probe_structure
has_substantive_gate = any(
    gate is not None
    for gate in (
        self.minimum_flow,
        required_structure,
        self.structure_percentile_min,
        self.minimum_carry,
        self.max_raw_calibrated_gap,
    )
)
if not has_substantive_gate:
    return ThemeKeyEvaluation(
        satisfied=False,
        permission=permission,
        reasons=("theme key policy has no substantive evidence gate",),
    )
```

Then continue the existing configured-gate checks unchanged.

In `src/decision_lab/__init__.py`, import and add `"ThemeCalibrationState"` to `__all__`.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
pytest -q tests/test_themes.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/decision_lab/themes.py src/decision_lab/__init__.py tests/test_themes.py
git commit -m "feat: make ThemeKey calibration fail closed"
```

---

### Task 2: Migrate DataCenter and Genomics package calibration states

**Files:**
- Modify: `config/policies/theme_key_defaults.yaml`
- Modify: `config/themes/datacenter_infra.yaml`
- Modify: `config/themes/genomics_bio.yaml`
- Modify: `tests/test_theme_package_compat.py`
- Modify: `tests/test_genomics_bio_package.py`

**Interfaces:**
- Consumes: `ThemeCalibrationState` and `load_theme_package(...)` from Task 1.
- Produces: explicit package-level calibration states with no invented Genomics threshold.

- [ ] **Step 1: Write failing package configuration tests**

In `tests/test_theme_package_compat.py`, extend the DataCenter threshold test:

```python
from decision_lab.themes import ThemeCalibrationState, load_theme_package


def test_datacenter_thresholds_are_package_local():
    package = load_theme_package(ROOT / "config/themes/datacenter_infra.yaml")
    assert package.theme_key_policy.calibration_state is ThemeCalibrationState.OPERATIONAL
    assert package.theme_key_policy.minimum_flow == 0.50
    assert package.theme_key_policy.probe_structure == 0.08
    assert package.theme_key_policy.full_structure == 0.35
    assert package.theme_key_policy.minimum_valid_sessions == 2
```

In `tests/test_genomics_bio_package.py`, replace the temporary percentile assertion:

```python
from decision_lab.themes import ThemeCalibrationState, load_theme_package


def test_genomics_bio_is_explicitly_uncalibrated_and_has_no_invented_threshold():
    package = load_theme_package(ROOT / "config/themes/genomics_bio.yaml")

    policy = package.theme_key_policy
    assert policy.calibration_state is ThemeCalibrationState.UNCALIBRATED
    assert policy.minimum_flow is None
    assert policy.probe_structure is None
    assert policy.full_structure is None
    assert policy.structure_percentile_min is None
    assert policy.minimum_valid_sessions == 3

    result = policy.evaluate(
        flow=1.0,
        structure=1.0,
        structure_percentile=1.0,
        valid_sessions=100,
        permission="probe",
    )
    assert not result.satisfied
    assert result.reasons == ("theme key policy uncalibrated",)
```

- [ ] **Step 2: Run package tests and verify RED**

Run:

```bash
pytest -q tests/test_theme_package_compat.py tests/test_genomics_bio_package.py
```

Expected: FAIL because YAML files do not yet declare the required calibration states and Genomics still contains `structure_percentile_min: 0.80`.

- [ ] **Step 3: Update configuration**

Set `config/policies/theme_key_defaults.yaml` to include:

```yaml
version: "1.0"
calibration_state: uncalibrated
minimum_flow: null
probe_structure: null
full_structure: null
structure_percentile_min: null
minimum_valid_sessions: 1
minimum_carry: null
max_raw_calibrated_gap: null
```

Update `config/themes/datacenter_infra.yaml`:

```yaml
theme_key_policy:
  calibration_state: operational
  minimum_flow: 0.50
  probe_structure: 0.08
  full_structure: 0.35
  minimum_valid_sessions: 2
```

Update `config/themes/genomics_bio.yaml`:

```yaml
theme_key_policy:
  calibration_state: uncalibrated
  minimum_valid_sessions: 3
```

Delete `structure_percentile_min: 0.80` from Genomics.

Because PyYAML returns the calibration state as a string, update `load_theme_package(...)` in `src/decision_lab/themes.py` before constructing `ThemeKeyPolicy`:

```python
policy_payload = dict(payload.get("theme_key_policy", {}))
policy_payload["calibration_state"] = ThemeCalibrationState(
    policy_payload.get("calibration_state", "uncalibrated")
)
policy = ThemeKeyPolicy(**policy_payload)
```

- [ ] **Step 4: Run package tests and verify GREEN**

Run:

```bash
pytest -q tests/test_theme_package_compat.py tests/test_genomics_bio_package.py
```

Expected: PASS.

- [ ] **Step 5: Run the complete test suite**

Run:

```bash
pytest -q
```

Expected: all tests PASS. If any pre-existing test assumed an empty `ThemeKeyPolicy` could pass, update that test only if it contradicts the approved fail-closed spec.

- [ ] **Step 6: Commit**

```bash
git add config/policies/theme_key_defaults.yaml config/themes/datacenter_infra.yaml config/themes/genomics_bio.yaml src/decision_lab/themes.py tests/test_theme_package_compat.py tests/test_genomics_bio_package.py
git commit -m "config: declare ThemeKey calibration readiness"
```

---

### Task 3: Final safety audit and regression verification

**Files:**
- Review only: `src/decision_lab/tape.py`
- Review only: `src/decision_lab/playbooks.py`
- Review only: `src/decision_lab/hierarchical.py`
- Review only: `src/decision_lab/ledger.py`
- Verify changed Python/tests from Tasks 1-2.
- No product code changes unless a failing test demonstrates a direct regression caused by this correction.

**Interfaces:**
- Consumes: final branch from Tasks 1-2.
- Produces: verified PR state with fail-closed ThemeKey semantics and unchanged Tape/router/linkage/ledger behavior.

- [ ] **Step 1: Run full regression suite**

Run:

```bash
pytest -q
```

Expected: all tests PASS, including existing Tape/A-H/linkage/ledger tests.

- [ ] **Step 2: Run changed-files Ruff**

Run:

```bash
python -m ruff check   src/decision_lab/themes.py   src/decision_lab/__init__.py   src/decision_lab/adapters.py   tests/test_themes.py   tests/test_theme_package_compat.py   tests/test_genomics_bio_package.py   tests/test_biotech_adapter.py
```

Expected: exit 0 with no errors.

- [ ] **Step 3: Audit forbidden semantic drift**

Run/read checks equivalent to:

```bash
git diff main...HEAD -- src/decision_lab/tape.py src/decision_lab/playbooks.py src/decision_lab/hierarchical.py src/decision_lab/ledger.py
```

Expected: no changes.

Also verify:

```bash
grep -R "structure_percentile_min: 0.80" config/themes/genomics_bio.yaml
```

Expected: no match.

And verify DataCenter thresholds remain exactly:

```text
minimum_flow = 0.50
probe_structure = 0.08
full_structure = 0.35
minimum_valid_sessions = 2
calibration_state = operational
```

- [ ] **Step 4: Review PR diff against the spec**

Check that:

- no new calibration algorithm was invented;
- no Genomics threshold was retained;
- no current theme is marked `validated`;
- `uncalibrated` cannot become actionable regardless of strong flow/structure inputs;
- no live ledger path was enabled;
- no unrelated refactor entered the PR.

- [ ] **Step 5: Commit only if audit requires test/document cleanup**

If no cleanup is needed, do not create an empty commit. If a direct audit fix is required:

```bash
git add <only-directly-related-files>
git commit -m "test: close ThemeKey calibration regression gaps"
```

- [ ] **Step 6: Final verification evidence**

Run fresh on the exact final tree:

```bash
pytest -q
python -m ruff check   src/decision_lab/themes.py   src/decision_lab/__init__.py   src/decision_lab/adapters.py   tests/test_themes.py   tests/test_theme_package_compat.py   tests/test_genomics_bio_package.py   tests/test_biotech_adapter.py
```

Record the exact pytest pass count and Ruff exit status before claiming completion. Keep PR #2 unmerged until this evidence is green.
