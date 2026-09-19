from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml

from .universe import ThemeUniverse


class ThemeLifecycleState(str, Enum):
    DISCOVERY = "discovery"
    FORMING = "forming"
    STRENGTHENING = "strengthening"
    MATURE = "mature"
    WEAKENING = "weakening"
    DORMANT = "dormant"
    RETIRED = "retired"


class ThemeCalibrationState(str, Enum):
    UNCALIBRATED = "uncalibrated"
    OPERATIONAL = "operational"
    VALIDATED = "validated"


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
    calibration_state: ThemeCalibrationState = ThemeCalibrationState.UNCALIBRATED
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
        if self.calibration_state not in (
            ThemeCalibrationState.OPERATIONAL,
            ThemeCalibrationState.VALIDATED,
        ):
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

        reasons: list[str] = []
        if valid_sessions < self.minimum_valid_sessions:
            reasons.append("insufficient valid sessions")
        if self.minimum_flow is not None and (flow is None or flow < self.minimum_flow):
            reasons.append("flow condition not satisfied")
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
        versions = self._versions.get(key, [])
        if any(item.version == definition.version for item in versions):
            raise ValueError(f"duplicate theme version: {key}@{definition.version}")

        identifiers = (key, *definition.aliases)
        for identifier in identifiers:
            existing = self._aliases.get(identifier.lower())
            if existing is not None and existing != key:
                raise ValueError(f"alias collision: {identifier}")

        versions = self._versions.setdefault(key, [])
        versions.append(definition)
        versions.sort(key=lambda item: item.effective_from or "")
        for identifier in identifiers:
            self._aliases[identifier.lower()] = key

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

    policy_payload = dict(payload.get("theme_key_policy", {}))
    policy_payload["calibration_state"] = ThemeCalibrationState(
        policy_payload.get("calibration_state", "uncalibrated")
    )
    policy = ThemeKeyPolicy(**policy_payload)
    return ThemePackage(
        definition=definition,
        universe=universe,
        theme_key_policy=policy,
        evidence_adapter=str(payload.get("evidence_adapter", "generic")),
        version=str(payload.get("version", "1")),
        source_path=str(package_path),
    )
