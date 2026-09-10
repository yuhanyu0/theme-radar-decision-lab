from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

VALID_CANDIDATE_STATES = {
    "discovery",
    "provisional",
    "validated",
    "watch_only",
    "executable_candidate",
    "retired",
}

VALID_EXPRESSION_ROLES = {
    "beta_proxy",
    "quality_alpha",
    "high_beta_satellite",
    "second_order_beneficiary",
    "weak_or_unstable",
    "unclassified",
}


@dataclass(frozen=True)
class Candidate:
    ticker: str
    theme: str
    layer: str
    membership_state: str = "discovery"
    expression_role: str = "unclassified"
    economic_exposure: float | None = None
    evidence_strength: float | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    provenance: tuple[str, ...] = ()
    notes: str = ""

    def validate(self) -> None:
        if self.membership_state not in VALID_CANDIDATE_STATES:
            raise ValueError(f"invalid membership_state: {self.membership_state}")
        if self.expression_role not in VALID_EXPRESSION_ROLES:
            raise ValueError(f"invalid expression_role: {self.expression_role}")
        for name, value in {
            "economic_exposure": self.economic_exposure,
            "evidence_strength": self.evidence_strength,
        }.items():
            if value is not None and not (0.0 <= value <= 1.0):
                raise ValueError(f"{name} must be within [0, 1]")


@dataclass(frozen=True)
class ThemeLayer:
    name: str
    description: str = ""


@dataclass
class ThemeUniverse:
    theme: str
    layers: dict[str, ThemeLayer] = field(default_factory=dict)
    candidates: dict[str, Candidate] = field(default_factory=dict)
    version: str = "0.1"
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def add_layer(self, layer: ThemeLayer) -> None:
        self.layers[layer.name] = layer

    def add_candidate(self, candidate: Candidate) -> None:
        candidate.validate()
        if candidate.theme != self.theme:
            raise ValueError(
                f"candidate theme {candidate.theme!r} does not match universe {self.theme!r}"
            )
        if candidate.layer not in self.layers:
            raise ValueError(f"unknown theme layer: {candidate.layer}")
        self.candidates[candidate.ticker.upper()] = candidate

    def active_candidates(self) -> list[Candidate]:
        return [
            candidate
            for candidate in self.candidates.values()
            if candidate.membership_state != "retired"
        ]

    def by_layer(self, layer: str) -> list[Candidate]:
        return [c for c in self.active_candidates() if c.layer == layer]

    def symbols(self) -> list[str]:
        return sorted(c.ticker.upper() for c in self.active_candidates())

    @classmethod
    def from_records(
        cls,
        theme: str,
        layers: Iterable[dict],
        candidates: Iterable[dict],
        *,
        version: str = "0.1",
    ) -> "ThemeUniverse":
        universe = cls(theme=theme, version=version)
        for item in layers:
            universe.add_layer(ThemeLayer(**item))
        for item in candidates:
            if isinstance(item.get("provenance"), list):
                item = dict(item)
                item["provenance"] = tuple(item["provenance"])
            universe.add_candidate(Candidate(**item))
        return universe
