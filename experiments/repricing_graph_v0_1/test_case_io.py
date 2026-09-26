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


CASE = Path("experiments/repricing_graph_v0_1/cases/ETN_2026Q2_shadow.yaml")
THEME = Path("config/themes/datacenter_infra.yaml")


def _payload():
    return yaml.safe_load(CASE.read_text())


def _write(tmp_path, payload):
    path = tmp_path / "case.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return path


def test_real_shadow_case_loads_but_does_not_claim_candidate():
    case = load_shadow_case(CASE)
    assert case.ticker == "ETN"
    assert case.theme_id == "DataCenter_Infra"
    assert case.primary_fundamental_variable == "ETN_FY2026_ADJUSTED_EPS"
    assert case.status == "RESEARCHING"
    assert case.market_expectation.method is MarketExpectationMethod.SELL_SIDE_CONSENSUS


def test_vertical_slice_rejects_non_etn_target(tmp_path):
    payload = _payload()
    payload["ticker"] = "VRT"
    with pytest.raises(ValueError, match="ETN"):
        load_shadow_case(_write(tmp_path, payload))


def test_vertical_slice_rejects_wrong_theme_or_layer(tmp_path):
    for key, value in (
        ("theme_id", "OtherTheme"),
        ("layer", "thermal_liquid_cooling"),
    ):
        payload = _payload()
        payload[key] = value
        with pytest.raises(ValueError):
            load_shadow_case(_write(tmp_path, payload))


def test_case_rejects_evidence_available_after_as_of(tmp_path):
    payload = _payload()
    payload["sources"][0]["available_at"] = "2026-09-27T00:00:00+00:00"
    with pytest.raises(ValueError, match="available_at"):
        load_shadow_case(_write(tmp_path, payload))


def test_case_rejects_missing_source_provenance(tmp_path):
    payload = _payload()
    payload["sources"][0]["url"] = ""
    with pytest.raises(ValueError, match="source"):
        load_shadow_case(_write(tmp_path, payload))


def test_consensus_requires_explicit_availability_timestamp(tmp_path):
    payload = _payload()
    payload["market_expectation"]["available_at"] = None
    with pytest.raises((TypeError, ValueError), match="available_at"):
        load_shadow_case(_write(tmp_path, payload))


def test_management_guidance_cannot_be_labeled_sell_side_consensus(tmp_path):
    payload = _payload()
    market_source = next(
        item for item in payload["sources"]
        if item["source_id"] == payload["market_expectation"]["source_id"]
    )
    market_source["source_kind"] = "management_guidance"
    with pytest.raises(ValueError, match="SELL_SIDE_CONSENSUS"):
        load_shadow_case(_write(tmp_path, payload))


def test_catalyst_known_only_after_case_as_of_is_rejected(tmp_path):
    payload = _payload()
    payload["catalysts"][0]["available_at"] = "2026-09-27T00:00:00+00:00"
    with pytest.raises(ValueError, match="catalyst"):
        load_shadow_case(_write(tmp_path, payload))


def test_vertical_slice_rejects_case_before_theme_effective_date():
    case = load_shadow_case(CASE)
    package = load_theme_package(THEME)
    early = replace(case, as_of="2026-08-31T20:00:00+00:00")
    with pytest.raises(ValueError, match="effective"):
        validate_etn_vertical_slice_case(early, package)


def test_vertical_slice_checks_etn_layer_against_package():
    case = load_shadow_case(CASE)
    package = load_theme_package(THEME)
    validate_etn_vertical_slice_case(case, package)
    assert package.universe.candidates["ETN"].layer == "electrical_switchgear"


def test_future_outcomes_cannot_be_embedded_in_case_input(tmp_path):
    payload = _payload()
    payload["realized_20d_return"] = 0.25
    with pytest.raises(ValueError, match="future outcome"):
        load_shadow_case(_write(tmp_path, payload))


def test_price_implied_expectation_requires_recorded_assumptions(tmp_path):
    payload = _payload()
    payload["market_expectation"]["method"] = "PRICE_IMPLIED"
    payload["market_expectation"]["assumptions"] = []
    market_source = next(
        item for item in payload["sources"]
        if item["source_id"] == payload["market_expectation"]["source_id"]
    )
    market_source["source_kind"] = "price_implied"
    with pytest.raises(ValueError, match="assumptions"):
        load_shadow_case(_write(tmp_path, payload))


def test_point_in_time_validator_is_pure_on_loaded_case():
    case = load_shadow_case(CASE)
    validate_point_in_time_case(case)
    assert case.status == "RESEARCHING"
