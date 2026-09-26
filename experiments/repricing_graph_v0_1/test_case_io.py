from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from decision_lab.themes import load_theme_package
from experiments.repricing_graph_v0_1.case_io import (
    load_shadow_case,
    validate_etn_vertical_slice_case,
    validate_point_in_time_case,
)
from experiments.repricing_graph_v0_1.model import MarketExpectationMethod

CASE=Path(__file__).parent / "cases" / "ETN_2026Q2_shadow.yaml"


def package(effective_from="2026-09-01"):
    repo_root = Path(__file__).resolve().parents[2]
    loaded = load_theme_package(repo_root / "config" / "themes" / "datacenter_infra.yaml")
    return replace(
        loaded,
        definition=replace(loaded.definition, effective_from=effective_from),
    )

