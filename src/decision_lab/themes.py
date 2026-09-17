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
