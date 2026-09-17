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


def test_new_market_wide_interfaces_are_publicly_importable():
    import decision_lab

    assert decision_lab.ThemeRegistry is not None
    assert decision_lab.ThemePackage is not None
    assert decision_lab.ThemeKeyPolicy is not None
    assert decision_lab.GenericEvidenceAdapter is not None
    assert decision_lab.IndustrialsInfrastructureAdapter is not None
    assert decision_lab.HierarchicalControlSpec is not None
    assert decision_lab.hierarchical_linkage is not None
