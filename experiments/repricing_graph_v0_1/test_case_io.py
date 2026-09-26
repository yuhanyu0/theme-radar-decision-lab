from dataclasses import replace
from pathlib import Path

from decision_lab.themes import load_theme_package

CASE=Path(__file__).parent / "cases" / "ETN_2026Q2_shadow.yaml"


def package(effective_from="2026-09-01"):
    repo_root = Path(__file__).resolve().parents[2]
    loaded = load_theme_package(repo_root / "config" / "themes" / "datacenter_infra.yaml")
    return replace(
        loaded,
        definition=replace(loaded.definition, effective_from=effective_from),
    )

