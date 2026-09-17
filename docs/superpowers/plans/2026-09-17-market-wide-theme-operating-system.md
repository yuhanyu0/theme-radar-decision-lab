# Market-wide Theme Operating System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first market-wide abstraction spine so `DataCenter_Infra` runs as a normal theme package through generic registry, policy, evidence-adapter, and hierarchical-control interfaces without changing existing Tape or A-H routing semantics.

**Architecture:** Add first-class theme lifecycle/policy/package objects above the existing `ThemeUniverse`, preserve the legacy DataCenter seed as a compatibility source, normalize company evidence through small adapters, and add target-excluded hierarchical market/sector/industry/theme linkage diagnostics. Keep all new behavior additive and public-safe; do not enable live decision logging.

**Tech Stack:** Python 3.11+, dataclasses/Enum/Protocol, NumPy, pandas, PyYAML, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-17-market-wide-theme-operating-system-design.md`

## Global Constraints

- `theme-radar-log` remains model output/evidence, never ground truth.
- The universal dual-key rule remains unchanged: one key only => `WATCH_ONLY`; failed/falling Tape => `BLOCKED`.
- DataCenter absolute thresholds (`flow ~0.50`, probe structure `~0.08`, full structure `~0.35`) must remain package-local and must not become global defaults.
- A ticker must never appear in its own theme control; identity-like controls must be rejected or explicitly warned.
- Missing valid controls must return `coverage_pending`, never fabricated linkage metrics.
- Candidate membership/effective-time changes must not retroactively alter historical theme baskets.
- Existing `TapeAssessment`, `assess_tape_state`, `route_playbooks`, ledger, and outcome semantics must remain backward compatible.
- Keep `config/datacenter_seed.example.yaml` loadable until compatibility tests prove the new package path is equivalent.
- The repository is public; do not enable or write real `ledger/live` decisions.
- No World Scanner, second live theme, portfolio sizing, or brokerage execution in this increment.

---

## File structure for this increment

Create focused modules rather than enlarging existing ones:

```text
src/decision_lab/themes.py        # Theme lifecycle, registry, key policy, package loading
src/decision_lab/adapters.py      # Raw company facts -> normalized evidence contracts
src/decision_lab/hierarchical.py  # Market/sector/industry/theme target-excluded linkage

config/themes/datacenter_infra.yaml
config/policies/theme_key_defaults.yaml
config/adapters/industrials_infrastructure.yaml

tests/test_themes.py
tests/test_adapters.py
tests/test_hierarchical.py
tests/test_theme_package_compat.py
```

Modify only:

```text
src/decision_lab/__init__.py
README.md
```

Do not modify `tape.py` or `playbooks.py` except if a regression test exposes an actual compatibility break.

---

### Task 1: Theme lifecycle, registry, and package-local ThemeKeyPolicy

**Files:**
- Create: `src/decision_lab/themes.py`
- Create: `tests/test_themes.py`

**Interfaces:**
- Produces: `ThemeLifecycleState`, `ThemeDefinition`, `ThemeKeyPolicy`, `ThemeKeyEvaluation`, `ThemeRegistry`.
- Later tasks rely on `ThemeDefinition.theme_id`, `ThemeRegistry.register()`, `ThemeRegistry.resolve()`, and `ThemeKeyPolicy.evaluate()`.

- [ ] **Step 1: Write failing lifecycle/policy tests**

Create `tests/test_themes.py` with these first tests:

```python
from decision_lab.themes import (
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemeLifecycleState,
    ThemeRegistry,
)


def test_registry_resolves_alias_and_preserves_historical_versions():
    registry = ThemeRegistry()
    v1 = ThemeDefinition(
        theme_id="Grid_Modernization",
        display_name="Grid Modernization",
        aliases=("Grid",),
        lifecycle_state=ThemeLifecycleState.FORMING,
        effective_from="2026-01-01",
        version="1",
    )
    v2 = ThemeDefinition(
        theme_id="Grid_Modernization",
        display_name="Grid Modernization",
        aliases=("Grid",),
        lifecycle_state=ThemeLifecycleState.STRENGTHENING,
        effective_from="2026-06-01",
        version="2",
    )
    registry.register(v1)
    registry.register(v2)

    assert registry.resolve("Grid", as_of="2026-03-01").version == "1"
    assert registry.resolve("Grid_Modernization", as_of="2026-07-01").version == "2"
    assert registry.latest("Grid").lifecycle_state is ThemeLifecycleState.STRENGTHENING


def test_parent_child_relationships_reject_self_parent():
    definition = ThemeDefinition(
        theme_id="Defense_Autonomy",
        display_name="Defense Autonomy",
        parent_theme_id="Defense_Autonomy",
        version="1",
    )
    try:
        definition.validate()
    except ValueError as exc:
        assert "parent" in str(exc).lower()
    else:
        raise AssertionError("self-parent theme must be rejected")


def test_global_theme_key_policy_has_no_datacenter_thresholds():
    policy = ThemeKeyPolicy()
    assert policy.minimum_flow is None
    assert policy.probe_structure is None
    assert policy.full_structure is None


def test_theme_key_policy_requires_all_configured_inputs():
    policy = ThemeKeyPolicy(
        minimum_flow=0.50,
        probe_structure=0.08,
        full_structure=0.35,
        minimum_valid_sessions=2,
    )
    assert policy.evaluate(flow=0.52, structure=0.10, valid_sessions=2, permission="probe").satisfied
    assert not policy.evaluate(flow=0.52, structure=None, valid_sessions=2, permission="probe").satisfied
    assert not policy.evaluate(flow=0.52, structure=0.10, valid_sessions=1, permission="probe").satisfied
    assert policy.evaluate(flow=0.52, structure=0.36, valid_sessions=2, permission="full").satisfied
```

- [ ] **Step 2: Run the tests and verify they fail because `decision_lab.themes` does not exist**

Run:

```bash
python -m pytest tests/test_themes.py -q
```

Expected: collection/import failure for `decision_lab.themes`.

- [ ] **Step 3: Implement the minimal lifecycle/registry/policy module**

Create `src/decision_lab/themes.py` with these public types and signatures:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class ThemeLifecycleState(str, Enum):
    DISCOVERY = "discovery"
    FORMING = "forming"
    STRENGTHENING = "strengthening"
    MATURE = "mature"
    WEAKENING = "weakening"
    DORMANT = "dormant"
    RETIRED = "retired"


@dataclass(frozen=True)
class ThemeDefinition:
    theme_id: str
    display_name: str
    aliases: tuple[str, ...] = ()
    lifecycle_state: ThemeLifecycleState = ThemeLifecycleState.DISCOVERY
    discovered_at: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    parent_theme_id: str | None = None
    child_theme_ids: tuple[str, ...] = ()
    thesis_summary: str = ""
    economic_chain_description: str = ""
    benchmark_stack: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    version: str = "1"

    def validate(self) -> None:
        if not self.theme_id.strip():
            raise ValueError("theme_id must be non-empty")
        if self.parent_theme_id == self.theme_id:
            raise ValueError("theme cannot be its own parent")
        if self.theme_id in self.child_theme_ids:
            raise ValueError("theme cannot be its own child")
        if self.effective_from and self.effective_to and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")


@dataclass(frozen=True)
class ThemeKeyEvaluation:
    satisfied: bool
    permission: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ThemeKeyPolicy:
    minimum_flow: float | None = None
    probe_structure: float | None = None
    full_structure: float | None = None
    structure_percentile_min: float | None = None
    minimum_valid_sessions: int = 1
    minimum_carry: float | None = None
    max_raw_calibrated_gap: float | None = None

    def evaluate(
        self,
        *,
        flow: float | None,
        structure: float | None,
        valid_sessions: int,
        permission: Literal["probe", "full"] = "probe",
        structure_percentile: float | None = None,
        carry: float | None = None,
        raw_calibrated_gap: float | None = None,
    ) -> ThemeKeyEvaluation:
        reasons: list[str] = []
        if valid_sessions < self.minimum_valid_sessions:
            reasons.append("insufficient valid sessions")
        if self.minimum_flow is not None and (flow is None or flow < self.minimum_flow):
            reasons.append("flow condition not satisfied")
        required_structure = self.full_structure if permission == "full" else self.probe_structure
        if required_structure is not None and (
            structure is None or structure < required_structure
        ):
            reasons.append("structure condition not satisfied")
        if self.structure_percentile_min is not None and (
            structure_percentile is None
            or structure_percentile < self.structure_percentile_min
        ):
            reasons.append("structure percentile condition not satisfied")
        if self.minimum_carry is not None and (carry is None or carry < self.minimum_carry):
            reasons.append("carry condition not satisfied")
        if self.max_raw_calibrated_gap is not None and (
            raw_calibrated_gap is None
            or abs(raw_calibrated_gap) > self.max_raw_calibrated_gap
        ):
            reasons.append("raw/calibrated inconsistency exceeds policy")
        return ThemeKeyEvaluation(not reasons, permission, tuple(reasons))


@dataclass
class ThemeRegistry:
    _versions: dict[str, list[ThemeDefinition]] = field(default_factory=dict)
    _aliases: dict[str, str] = field(default_factory=dict)

    def register(self, definition: ThemeDefinition) -> None:
        definition.validate()
        key = definition.theme_id
        versions = self._versions.setdefault(key, [])
        if any(item.version == definition.version for item in versions):
            raise ValueError(f"duplicate theme version: {key}@{definition.version}")
        versions.append(definition)
        versions.sort(key=lambda item: item.effective_from or "")
        self._aliases[key.lower()] = key
        for alias in definition.aliases:
            existing = self._aliases.get(alias.lower())
            if existing is not None and existing != key:
                raise ValueError(f"alias collision: {alias}")
            self._aliases[alias.lower()] = key

    def _theme_id(self, identifier: str) -> str:
        try:
            return self._aliases[identifier.lower()]
        except KeyError as exc:
            raise KeyError(f"unknown theme: {identifier}") from exc

    def latest(self, identifier: str) -> ThemeDefinition:
        return self._versions[self._theme_id(identifier)][-1]

    def resolve(self, identifier: str, *, as_of: str | None = None) -> ThemeDefinition:
        versions = self._versions[self._theme_id(identifier)]
        if as_of is None:
            return versions[-1]
        valid = [
            item
            for item in versions
            if (item.effective_from is None or item.effective_from <= as_of)
            and (item.effective_to is None or as_of < item.effective_to)
        ]
        if not valid:
            raise KeyError(f"no theme version active at {as_of}: {identifier}")
        return valid[-1]
```

- [ ] **Step 4: Run Task 1 tests**

Run:

```bash
python -m pytest tests/test_themes.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/decision_lab/themes.py tests/test_themes.py
git commit -m "feat: add theme registry and key policy"
```

---

### Task 2: Generic ThemePackage loader and DataCenter compatibility package

**Files:**
- Modify: `src/decision_lab/themes.py`
- Create: `config/themes/datacenter_infra.yaml`
- Create: `config/policies/theme_key_defaults.yaml`
- Create: `tests/test_theme_package_compat.py`
- Keep unchanged: `config/datacenter_seed.example.yaml`

**Interfaces:**
- Produces: `ThemePackage`, `load_theme_package(path)`.
- Consumes: existing `ThemeUniverse.from_records()` and Task 1 types.

- [ ] **Step 1: Write failing compatibility tests**

Create `tests/test_theme_package_compat.py`:

```python
from pathlib import Path

import yaml

from decision_lab.themes import load_theme_package
from decision_lab.universe import ThemeUniverse


ROOT = Path(__file__).resolve().parents[1]


def _legacy_universe() -> ThemeUniverse:
    payload = yaml.safe_load((ROOT / "config/datacenter_seed.example.yaml").read_text())
    return ThemeUniverse.from_records(
        theme=payload["theme"],
        layers=payload["layers"],
        candidates=payload["candidates"],
        version=payload["version"],
    )


def test_datacenter_loads_as_generic_theme_package_without_semantic_universe_drift():
    package = load_theme_package(ROOT / "config/themes/datacenter_infra.yaml")
    legacy = _legacy_universe()

    assert package.definition.theme_id == "DataCenter_Infra"
    assert package.universe.theme == "DataCenter_Infra"
    assert package.universe.symbols() == legacy.symbols()
    assert set(package.universe.layers) == set(legacy.layers)
    assert package.universe.version == legacy.version


def test_datacenter_thresholds_are_package_local():
    package = load_theme_package(ROOT / "config/themes/datacenter_infra.yaml")
    assert package.theme_key_policy.minimum_flow == 0.50
    assert package.theme_key_policy.probe_structure == 0.08
    assert package.theme_key_policy.full_structure == 0.35


def test_candidate_effective_time_survives_package_loading():
    package = load_theme_package(ROOT / "config/themes/datacenter_infra.yaml")
    assert package.universe.candidates["QCOM"].effective_from == "2026-09-08"
    assert package.universe.candidates["ENPH"].effective_from == "2026-09-08"
```

- [ ] **Step 2: Run the compatibility tests and verify failure**

Run:

```bash
python -m pytest tests/test_theme_package_compat.py -q
```

Expected: import/file failure because `ThemePackage`/package config do not exist yet.

- [ ] **Step 3: Add package data type and loader**

Append to `src/decision_lab/themes.py` imports and implementation:

```python
from pathlib import Path

import yaml

from .universe import ThemeUniverse


@dataclass(frozen=True)
class ThemePackage:
    definition: ThemeDefinition
    universe: ThemeUniverse
    theme_key_policy: ThemeKeyPolicy
    evidence_adapter: str
    version: str
    source_path: str


def _as_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    raise TypeError("expected a list/tuple")


def load_theme_package(path: str | Path) -> ThemePackage:
    package_path = Path(path)
    payload = yaml.safe_load(package_path.read_text())
    theme_payload = dict(payload["theme"])
    theme_payload["aliases"] = _as_tuple(theme_payload.get("aliases"))
    theme_payload["child_theme_ids"] = _as_tuple(theme_payload.get("child_theme_ids"))
    theme_payload["benchmark_stack"] = _as_tuple(theme_payload.get("benchmark_stack"))
    theme_payload["provenance"] = _as_tuple(theme_payload.get("provenance"))
    theme_payload["lifecycle_state"] = ThemeLifecycleState(
        theme_payload.get("lifecycle_state", "discovery")
    )
    definition = ThemeDefinition(**theme_payload)
    definition.validate()

    universe_path = (package_path.parent / payload["universe_source"]).resolve()
    universe_payload = yaml.safe_load(universe_path.read_text())
    universe = ThemeUniverse.from_records(
        theme=universe_payload["theme"],
        layers=universe_payload["layers"],
        candidates=universe_payload["candidates"],
        version=universe_payload.get("version", "0.1"),
    )
    if universe.theme != definition.theme_id:
        raise ValueError("theme package definition and universe source disagree")

    policy = ThemeKeyPolicy(**payload.get("theme_key_policy", {}))
    return ThemePackage(
        definition=definition,
        universe=universe,
        theme_key_policy=policy,
        evidence_adapter=str(payload.get("evidence_adapter", "generic")),
        version=str(payload.get("version", "1")),
        source_path=str(package_path),
    )
```

- [ ] **Step 4: Add public-safe package configuration**

Create `config/themes/datacenter_infra.yaml`:

```yaml
version: "1.0"

theme:
  theme_id: DataCenter_Infra
  display_name: Data Center Infrastructure
  aliases: [DataCenter, DC_Infra]
  lifecycle_state: strengthening
  discovered_at: "2026-09-01"
  effective_from: "2026-09-01"
  thesis_summary: "AI/data-center buildout creates cross-industry demand across power, grid, thermal, construction, networking, compute support and ownership."
  economic_chain_description: "Power/time-to-power -> grid/interconnection -> electrical/conversion -> thermal -> EPC/MEP -> networking/optics -> compute support -> ownership."
  benchmark_stack: [SPY, XLK, XLI, XLU]
  provenance: ["config/datacenter_seed.example.yaml"]
  version: "1"

universe_source: ../datacenter_seed.example.yaml
evidence_adapter: industrials_infrastructure

theme_key_policy:
  minimum_flow: 0.50
  probe_structure: 0.08
  full_structure: 0.35
  minimum_valid_sessions: 2
```

Create `config/policies/theme_key_defaults.yaml`:

```yaml
version: "1.0"
minimum_flow: null
probe_structure: null
full_structure: null
structure_percentile_min: null
minimum_valid_sessions: 1
minimum_carry: null
max_raw_calibrated_gap: null
```

- [ ] **Step 5: Run compatibility tests and existing universe/control tests**

Run:

```bash
python -m pytest tests/test_theme_package_compat.py tests/test_radar_and_controls.py -q
```

Expected: all pass; legacy seed remains loadable and package symbols/layers match exactly.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/decision_lab/themes.py config/themes/datacenter_infra.yaml config/policies/theme_key_defaults.yaml tests/test_theme_package_compat.py
git commit -m "feat: load DataCenter as generic theme package"
```

---

### Task 3: Company evidence adapter contract and industrials/infrastructure adapter

**Files:**
- Create: `src/decision_lab/adapters.py`
- Create: `config/adapters/industrials_infrastructure.yaml`
- Create: `tests/test_adapters.py`

**Interfaces:**
- Produces: `CompanyEvidenceInput`, `NormalizedCompanyEvidence`, `CompanyEvidenceAdapter`, `GenericEvidenceAdapter`, `IndustrialsInfrastructureAdapter`.
- Normalized evidence keeps `raw_facts` and provenance so inference never replaces source facts.

- [ ] **Step 1: Write failing adapter tests**

Create `tests/test_adapters.py`:

```python
from decision_lab.adapters import (
    CompanyEvidenceInput,
    GenericEvidenceAdapter,
    IndustrialsInfrastructureAdapter,
)


def test_generic_adapter_preserves_raw_facts_and_provenance():
    source = CompanyEvidenceInput(
        ticker="XYZ",
        as_of="2026-09-17",
        raw_facts={"revenue_growth": 0.12, "top_customer_share": 0.30},
        provenance=("sec:xyz-10q",),
    )
    result = GenericEvidenceAdapter().normalize(source)
    assert result.raw_facts == source.raw_facts
    assert result.provenance == ("sec:xyz-10q",)
    assert result.source_coverage == "raw_only"


def test_industrials_adapter_emits_bounded_common_contract():
    source = CompanyEvidenceInput(
        ticker="XYZ",
        as_of="2026-09-17",
        raw_facts={
            "revenue_growth": 0.20,
            "gross_margin": 0.35,
            "backlog_growth": 0.30,
            "order_growth": 0.25,
            "fcf_margin": 0.12,
            "net_debt_to_ebitda": 1.0,
            "top_customer_share": 0.28,
            "guidance_revision": 0.05,
        },
        provenance=("company-ir:q2",),
    )
    result = IndustrialsInfrastructureAdapter().normalize(source)
    assert 0.0 <= result.growth <= 1.0
    assert 0.0 <= result.demand_visibility <= 1.0
    assert 0.0 <= result.cash_generation <= 1.0
    assert 0.0 <= result.balance_sheet_strength <= 1.0
    assert result.customer_concentration == 0.28
    assert result.raw_facts["backlog_growth"] == 0.30
    assert result.source_coverage == "industrials_core"
```

- [ ] **Step 2: Verify failure before implementation**

Run:

```bash
python -m pytest tests/test_adapters.py -q
```

Expected: import failure for `decision_lab.adapters`.

- [ ] **Step 3: Implement adapter contracts and conservative normalization**

Create `src/decision_lab/adapters.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

import numpy as np


@dataclass(frozen=True)
class CompanyEvidenceInput:
    ticker: str
    as_of: str
    raw_facts: Mapping[str, float | int | str | None]
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedCompanyEvidence:
    ticker: str
    as_of: str
    growth: float | None = None
    margin_quality: float | None = None
    demand_visibility: float | None = None
    order_or_contract_visibility: float | None = None
    capital_intensity: float | None = None
    cash_generation: float | None = None
    balance_sheet_strength: float | None = None
    customer_concentration: float | None = None
    supply_constraint: float | None = None
    guidance_revision: float | None = None
    valuation_anchor_change: float | None = None
    thesis_risk: float | None = None
    source_coverage: str = "raw_only"
    provenance: tuple[str, ...] = ()
    raw_facts: Mapping[str, float | int | str | None] = None  # type: ignore[assignment]


class CompanyEvidenceAdapter(Protocol):
    def normalize(self, source: CompanyEvidenceInput) -> NormalizedCompanyEvidence: ...


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _linear(value: float | None, *, midpoint: float, span: float) -> float | None:
    if value is None:
        return None
    return _clip01(0.5 + (float(value) - midpoint) / span)


class GenericEvidenceAdapter:
    def normalize(self, source: CompanyEvidenceInput) -> NormalizedCompanyEvidence:
        return NormalizedCompanyEvidence(
            ticker=source.ticker.upper(),
            as_of=source.as_of,
            source_coverage="raw_only",
            provenance=source.provenance,
            raw_facts=dict(source.raw_facts),
        )


class IndustrialsInfrastructureAdapter:
    def normalize(self, source: CompanyEvidenceInput) -> NormalizedCompanyEvidence:
        facts = source.raw_facts
        revenue_growth = _number(facts.get("revenue_growth"))
        gross_margin = _number(facts.get("gross_margin"))
        backlog_growth = _number(facts.get("backlog_growth"))
        order_growth = _number(facts.get("order_growth"))
        capex_to_sales = _number(facts.get("capex_to_sales"))
        fcf_margin = _number(facts.get("fcf_margin"))
        leverage = _number(facts.get("net_debt_to_ebitda"))
        concentration = _number(facts.get("top_customer_share"))
        guidance = _number(facts.get("guidance_revision"))
        demand_candidates = [
            value for value in (_linear(backlog_growth, midpoint=0.0, span=0.60), _linear(order_growth, midpoint=0.0, span=0.60)) if value is not None
        ]
        demand = max(demand_candidates) if demand_candidates else None
        return NormalizedCompanyEvidence(
            ticker=source.ticker.upper(),
            as_of=source.as_of,
            growth=_linear(revenue_growth, midpoint=0.0, span=0.40),
            margin_quality=None if gross_margin is None else _clip01(gross_margin / 0.50),
            demand_visibility=demand,
            order_or_contract_visibility=demand,
            capital_intensity=None if capex_to_sales is None else _clip01(capex_to_sales / 0.25),
            cash_generation=None if fcf_margin is None else _clip01(fcf_margin / 0.20),
            balance_sheet_strength=None if leverage is None else _clip01(1.0 - leverage / 4.0),
            customer_concentration=None if concentration is None else _clip01(concentration),
            guidance_revision=_linear(guidance, midpoint=0.0, span=0.20),
            thesis_risk=None if concentration is None else _clip01(concentration),
            source_coverage="industrials_core",
            provenance=source.provenance,
            raw_facts=dict(facts),
        )


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
```

- [ ] **Step 4: Add public-safe adapter metadata**

Create `config/adapters/industrials_infrastructure.yaml`:

```yaml
version: "1.0"
adapter: industrials_infrastructure
expected_raw_fields:
  - revenue_growth
  - gross_margin
  - backlog_growth
  - order_growth
  - capex_to_sales
  - fcf_margin
  - net_debt_to_ebitda
  - top_customer_share
  - guidance_revision
notes: "Normalized scores are routing/research features, not replacements for primary-source raw facts."
```

- [ ] **Step 5: Run adapter tests and lint the module**

Run:

```bash
python -m pytest tests/test_adapters.py -q
python -m ruff check src/decision_lab/adapters.py tests/test_adapters.py
```

Expected: both commands pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/decision_lab/adapters.py config/adapters/industrials_infrastructure.yaml tests/test_adapters.py
git commit -m "feat: add company evidence adapter contract"
```

---

### Task 4: Hierarchical market/sector/industry/theme linkage with explicit pending coverage

**Files:**
- Create: `src/decision_lab/hierarchical.py`
- Create: `tests/test_hierarchical.py`

**Interfaces:**
- Produces: `HierarchicalControlSpec`, `HierarchicalLinkageResult`, `hierarchical_linkage()`.
- Inputs: ticker return series plus named control return series. Theme constituent metadata is required to prove target exclusion.

- [ ] **Step 1: Write failing hierarchy/circularity/pending tests**

Create `tests/test_hierarchical.py`:

```python
import numpy as np
import pandas as pd
import pytest

from decision_lab.hierarchical import (
    HierarchicalControlSpec,
    hierarchical_linkage,
)


def _series(values, name):
    idx = pd.date_range("2026-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx, name=name)


def test_hierarchical_linkage_estimates_incremental_theme_fit_without_target_leakage():
    rng = np.random.default_rng(42)
    n = 100
    market = rng.normal(0, 0.01, n)
    sector = 0.7 * market + rng.normal(0, 0.006, n)
    industry = 0.5 * sector + rng.normal(0, 0.005, n)
    theme = 0.4 * industry + rng.normal(0, 0.006, n)
    ticker = 0.2 * market + 0.3 * sector + 0.2 * industry + 0.9 * theme + rng.normal(0, 0.004, n)
    controls = {
        "market": _series(market, "SPY"),
        "sector": _series(sector, "XLK"),
        "industry": _series(industry, "industry"),
        "theme": _series(theme, "theme_minus_X"),
    }
    spec = HierarchicalControlSpec(
        target="X",
        market="market",
        sector="sector",
        industry="industry",
        theme="theme",
        theme_members=("A", "B", "C"),
    )
    result = hierarchical_linkage(_series(ticker, "X"), controls, spec, window=63)
    assert result.status == "ok"
    assert result.theme_beta is not None and result.theme_beta > 0
    assert result.r2 is not None and result.r2 > 0
    assert result.incremental_theme_r2 is not None and result.incremental_theme_r2 > 0
    assert result.circularity_warning is False


def test_hierarchical_control_rejects_target_membership():
    spec = HierarchicalControlSpec(
        target="X",
        market="market",
        theme="theme",
        theme_members=("A", "X"),
    )
    with pytest.raises(ValueError, match="target.*theme control"):
        spec.validate()


def test_identity_like_control_is_rejected():
    values = np.linspace(-0.01, 0.01, 100)
    target = _series(values, "X")
    controls = {
        "market": _series(np.sin(np.arange(100)) / 100, "SPY"),
        "theme": target.rename("bad_theme"),
    }
    spec = HierarchicalControlSpec(
        target="X",
        market="market",
        theme="theme",
        theme_members=("A", "B"),
    )
    with pytest.raises(ValueError, match="identity-like"):
        hierarchical_linkage(target, controls, spec, window=63)


def test_missing_theme_control_returns_coverage_pending():
    values = np.linspace(-0.01, 0.01, 100)
    target = _series(values, "X")
    controls = {"market": _series(np.sin(np.arange(100)) / 100, "SPY")}
    spec = HierarchicalControlSpec(
        target="X",
        market="market",
        theme="theme",
        theme_members=("A", "B"),
    )
    result = hierarchical_linkage(target, controls, spec, window=63)
    assert result.status == "coverage_pending"
    assert result.theme_beta is None
    assert "theme" in result.missing_controls
```

- [ ] **Step 2: Verify failure**

Run:

```bash
python -m pytest tests/test_hierarchical.py -q
```

Expected: import failure for `decision_lab.hierarchical`.

- [ ] **Step 3: Implement hierarchical control spec and multiple-regression diagnostics**

Create `src/decision_lab/hierarchical.py` with these exact public fields/signatures:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class HierarchicalControlSpec:
    target: str
    market: str
    theme: str
    sector: str | None = None
    industry: str | None = None
    theme_members: tuple[str, ...] = ()

    def validate(self) -> None:
        target = self.target.upper()
        if target in {member.upper() for member in self.theme_members}:
            raise ValueError("target must be excluded from theme control membership")
        names = [name for name in (self.market, self.sector, self.industry, self.theme) if name]
        if len(names) != len(set(names)):
            raise ValueError("hierarchical control names must be unique")

    def ordered_control_names(self) -> tuple[str, ...]:
        return tuple(name for name in (self.market, self.sector, self.industry, self.theme) if name)


@dataclass(frozen=True)
class HierarchicalLinkageResult:
    target: str
    status: str
    window: int
    observations: int
    theme_correlation: float | None
    theme_beta: float | None
    r2: float | None
    incremental_theme_r2: float | None
    residual_mean: float | None
    residual_vol: float | None
    circularity_warning: bool
    missing_controls: tuple[str, ...]
    coefficients: Mapping[str, float]


def hierarchical_linkage(
    target_returns: pd.Series,
    controls: Mapping[str, pd.Series],
    spec: HierarchicalControlSpec,
    *,
    window: int = 63,
) -> HierarchicalLinkageResult:
    spec.validate()
    required = spec.ordered_control_names()
    missing = tuple(name for name in required if name not in controls)
    if missing:
        return _pending(spec, window, len(target_returns.tail(window)), missing)

    joined = pd.concat(
        [target_returns.rename("target")]
        + [controls[name].rename(name) for name in required],
        axis=1,
    ).dropna().tail(window)
    n = len(joined)
    if n < max(10, window // 3):
        return _pending(spec, window, n, ())

    target_arr = joined["target"].to_numpy(float)
    for name in required:
        control_arr = joined[name].to_numpy(float)
        if np.allclose(target_arr, control_arr, rtol=1e-7, atol=1e-10):
            raise ValueError(f"identity-like control detected: {name}")

    X_controls = joined[list(required)].to_numpy(float)
    X = np.column_stack([np.ones(n), X_controls])
    coeff = np.linalg.lstsq(X, target_arr, rcond=None)[0]
    fitted = X @ coeff
    residual = target_arr - fitted
    ss_tot = float(np.sum((target_arr - target_arr.mean()) ** 2))
    ss_res = float(np.sum(residual**2))
    r2 = np.nan if ss_tot <= 1e-16 else 1.0 - ss_res / ss_tot

    without_theme = tuple(name for name in required if name != spec.theme)
    X_reduced = np.column_stack(
        [np.ones(n), joined[list(without_theme)].to_numpy(float)]
    )
    reduced_coeff = np.linalg.lstsq(X_reduced, target_arr, rcond=None)[0]
    reduced_residual = target_arr - (X_reduced @ reduced_coeff)
    reduced_ss = float(np.sum(reduced_residual**2))
    reduced_r2 = np.nan if ss_tot <= 1e-16 else 1.0 - reduced_ss / ss_tot
    incremental = None if not np.isfinite(r2) or not np.isfinite(reduced_r2) else max(0.0, float(r2 - reduced_r2))

    coefficients = {name: float(value) for name, value in zip(required, coeff[1:], strict=True)}
    theme_corr = float(joined["target"].corr(joined[spec.theme]))
    theme_beta = coefficients[spec.theme]
    circularity_warning = bool(
        abs(theme_corr) >= 0.995 and abs(theme_beta - 1.0) <= 0.03 and r2 >= 0.99
    )
    return HierarchicalLinkageResult(
        target=spec.target.upper(),
        status="ok",
        window=window,
        observations=n,
        theme_correlation=theme_corr,
        theme_beta=theme_beta,
        r2=None if not np.isfinite(r2) else float(r2),
        incremental_theme_r2=incremental,
        residual_mean=float(residual.mean()),
        residual_vol=float(residual.std(ddof=1)),
        circularity_warning=circularity_warning,
        missing_controls=(),
        coefficients=coefficients,
    )


def _pending(
    spec: HierarchicalControlSpec,
    window: int,
    observations: int,
    missing: tuple[str, ...],
) -> HierarchicalLinkageResult:
    return HierarchicalLinkageResult(
        target=spec.target.upper(),
        status="coverage_pending",
        window=window,
        observations=observations,
        theme_correlation=None,
        theme_beta=None,
        r2=None,
        incremental_theme_r2=None,
        residual_mean=None,
        residual_vol=None,
        circularity_warning=False,
        missing_controls=missing,
        coefficients={},
    )
```

- [ ] **Step 4: Run hierarchy tests and existing anti-circularity invariants**

Run:

```bash
python -m pytest tests/test_hierarchical.py tests/test_invariants.py -q
python -m ruff check src/decision_lab/hierarchical.py tests/test_hierarchical.py
```

Expected: all pass.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/decision_lab/hierarchical.py tests/test_hierarchical.py
git commit -m "feat: add hierarchical expression linkage"
```

---

### Task 5: Public API exports and package-level regression

**Files:**
- Modify: `src/decision_lab/__init__.py`
- Modify: `README.md`
- Modify: `tests/test_theme_package_compat.py`

**Interfaces:**
- Public package should expose new generic types without removing old exports.

- [ ] **Step 1: Add a failing public-import regression test**

Append to `tests/test_theme_package_compat.py`:

```python
def test_new_market_wide_interfaces_are_publicly_importable():
    import decision_lab

    assert decision_lab.ThemeRegistry is not None
    assert decision_lab.ThemePackage is not None
    assert decision_lab.ThemeKeyPolicy is not None
    assert decision_lab.GenericEvidenceAdapter is not None
    assert decision_lab.IndustrialsInfrastructureAdapter is not None
    assert decision_lab.HierarchicalControlSpec is not None
    assert decision_lab.hierarchical_linkage is not None
```

- [ ] **Step 2: Verify it fails before exports are added**

Run:

```bash
python -m pytest tests/test_theme_package_compat.py::test_new_market_wide_interfaces_are_publicly_importable -q
```

Expected: `AttributeError` on one of the new public interfaces.

- [ ] **Step 3: Export new interfaces from `src/decision_lab/__init__.py`**

Add imports:

```python
from .adapters import (
    CompanyEvidenceAdapter,
    CompanyEvidenceInput,
    GenericEvidenceAdapter,
    IndustrialsInfrastructureAdapter,
    NormalizedCompanyEvidence,
)
from .hierarchical import (
    HierarchicalControlSpec,
    HierarchicalLinkageResult,
    hierarchical_linkage,
)
from .themes import (
    ThemeDefinition,
    ThemeKeyEvaluation,
    ThemeKeyPolicy,
    ThemeLifecycleState,
    ThemePackage,
    ThemeRegistry,
    load_theme_package,
)
```

Add the same symbol names to `__all__` while preserving all existing exports.

- [ ] **Step 4: Update README scope language without changing safety invariants**

Replace the old MVP paragraph that says DataCenter is the pilot with text that states:

```markdown
## Market-wide architecture

`DataCenter_Infra` remains the first validated theme package, but the core engine is theme-agnostic. A `ThemeRegistry` manages theme lifecycle/versioning, each `ThemePackage` carries its own universe and Theme-key policy, company facts are normalized through evidence adapters, and hierarchical linkage separates broad-market/sector/industry movement from target-excluded theme linkage.

The current implementation increment intentionally does not add a global scanner or a second live theme yet. Its acceptance test is stricter: DataCenter must load through the generic package interface without semantic drift, while existing Tape, A-H routing, ledger, and outcome behavior stays unchanged.
```

Keep the existing repository-privacy warning intact.

- [ ] **Step 5: Run all tests and lint**

Run:

```bash
python -m pytest -q
python -m ruff check src tests
```

Expected: full suite passes; lint passes.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/decision_lab/__init__.py README.md tests/test_theme_package_compat.py
git commit -m "docs: expose market-wide theme interfaces"
```

---

### Task 6: Final compatibility verification and acceptance audit

**Files:**
- No production changes expected.
- If verification exposes a defect, fix only the smallest file responsible and add a regression test before changing behavior.

**Interfaces:**
- Confirms the increment satisfies the approved spec without starting Increment 2.

- [ ] **Step 1: Run focused compatibility matrix**

```bash
python -m pytest \
  tests/test_themes.py \
  tests/test_theme_package_compat.py \
  tests/test_adapters.py \
  tests/test_hierarchical.py \
  tests/test_invariants.py \
  tests/test_radar_and_controls.py \
  -q
```

Expected: all pass.

- [ ] **Step 2: Run complete project verification**

```bash
python -m pytest -q
python -m ruff check src tests
```

Expected: both commands pass with zero failures/errors.

- [ ] **Step 3: Verify no literal DataCenter dependency exists in core Python modules**

Run:

```bash
python - <<'PY'
from pathlib import Path
hits = []
for path in Path("src/decision_lab").glob("*.py"):
    text = path.read_text()
    if "DataCenter_Infra" in text or "datacenter_seed" in text:
        hits.append(str(path))
assert not hits, f"DataCenter literal leaked into core engine: {hits}"
print("PASS: no DataCenter literal in core engine")
PY
```

Expected: `PASS: no DataCenter literal in core engine`.

- [ ] **Step 4: Verify package-local thresholds and legacy compatibility in one executable check**

```bash
python - <<'PY'
from pathlib import Path
import yaml
from decision_lab.themes import ThemeKeyPolicy, load_theme_package
from decision_lab.universe import ThemeUniverse

root = Path(".")
package = load_theme_package(root / "config/themes/datacenter_infra.yaml")
legacy_payload = yaml.safe_load((root / "config/datacenter_seed.example.yaml").read_text())
legacy = ThemeUniverse.from_records(
    theme=legacy_payload["theme"],
    layers=legacy_payload["layers"],
    candidates=legacy_payload["candidates"],
    version=legacy_payload["version"],
)
assert ThemeKeyPolicy().minimum_flow is None
assert package.theme_key_policy.minimum_flow == 0.50
assert package.theme_key_policy.probe_structure == 0.08
assert package.theme_key_policy.full_structure == 0.35
assert package.universe.symbols() == legacy.symbols()
assert set(package.universe.layers) == set(legacy.layers)
print("PASS: generic package preserves DataCenter semantics without global threshold leakage")
PY
```

Expected: printed PASS line.

- [ ] **Step 5: Record verification commit only if a verification fix was necessary**

If no changes were needed, do not create an empty commit. If a defect was fixed, commit it with:

```bash
git add <only-files-changed-by-the-fix>
git commit -m "fix: close market-wide compatibility regression"
```

---

## Self-review against the approved spec

- Theme Registry/lifecycle: Task 1.
- Per-theme ThemeKeyPolicy with no DataCenter global leakage: Tasks 1–2 and Task 6 executable audit.
- DataCenter as a normal ThemePackage with legacy compatibility: Task 2.
- Evidence adapter interface + generic + industrials/infrastructure adapter: Task 3.
- Hierarchical market/sector/industry/theme diagnostics, target exclusion, circularity rejection, and `coverage_pending`: Task 4.
- Existing Tape/A-H semantics preserved: Task 6 runs all existing invariants unchanged.
- Public-safe repo/privacy posture preserved: no live ledger code/config is enabled anywhere in the plan.
- World Scanner, second theme, extra adapters, and calibration are intentionally deferred to later increments per the spec.

No placeholders remain in this plan. The first increment is independently testable and leaves the repository in a state where Increment 2 can onboard a genuinely different theme without modifying core execution semantics.
