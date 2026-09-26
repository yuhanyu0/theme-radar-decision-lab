from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from decision_lab.themes import load_theme_package
from experiments.repricing_graph_v0_1.case_io import (
    load_shadow_case,
    validate_etn_vertical_slice_case,
)

ROOT = Path(__file__).resolve().parents[2]
CASE_PATH = Path(__file__).with_name("cases") / "ETN_2026Q2_shadow.yaml"
PACKAGE_PATH = ROOT / "config" / "themes" / "datacenter_infra.yaml"


def _payload() -> dict:
    return yaml.safe_load(CASE_PATH.read_text())


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "case.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return path


def test_real_shadow_case_loads_and_is_etn_scoped():
    case = load_shadow_case(CASE_PATH)
    assert case.ticker == "ETN"
    assert case.theme_id == "DataCenter_Infra"
    assert case.primary_fundamental_variable == "ETN_FY2026_ADJUSTED_EPS"
    package = load_theme_package(PACKAGE_PATH)
    validate_etn_vertical_slice_case(case, package)


def test_rejects_non_etn_or_wrong_theme_vertical_slice(tmp_path):
    payload = _payload()
    payload["case"]["ticker"] = "VRT"
    path = _write(tmp_path, payload)
    case = load_shadow_case(path)
    with pytest.raises(ValueError, match="ETN"):
        validate_etn_vertical_slice_case(case, load_theme_package(PACKAGE_PATH))

    payload = _payload()
    payload["case"]["theme_id"] = "OtherTheme"
    path = _write(tmp_path, payload)
    case = load_shadow_case(path)
    with pytest.raises(ValueError, match="DataCenter"):
        validate_etn_vertical_slice_case(case, load_theme_package(PACKAGE_PATH))


def test_rejects_evidence_available_after_case_asof(tmp_path):
    payload = _payload()
    payload["sources"][0]["available_at"] = "2026-09-26T00:00:00+00:00"
    with pytest.raises(ValueError, match="available_at"):
        load_shadow_case(_write(tmp_path, payload))


def test_rejects_missing_source_provenance(tmp_path):
    payload = _payload()
    payload["sources"][0]["url"] = ""
    with pytest.raises(ValueError, match="source"):
        load_shadow_case(_write(tmp_path, payload))


def test_rejects_consensus_without_point_in_time_timestamp(tmp_path):
    payload = _payload()
    payload["market_expectation"]["available_at"] = None
    with pytest.raises(ValueError, match="available_at"):
        load_shadow_case(_write(tmp_path, payload))


def test_rejects_management_guidance_labeled_sell_side_consensus(tmp_path):
    payload = _payload()
    payload["market_expectation"]["source_id"] = "etn_q2_release"
    payload["market_expectation"]["method"] = "SELL_SIDE_CONSENSUS"
    with pytest.raises(ValueError, match="consensus"):
        load_shadow_case(_write(tmp_path, payload))


def test_rejects_catalyst_known_only_after_case_asof(tmp_path):
    payload = _payload()
    payload["catalysts"][0]["known_at"] = "2026-09-26T00:00:00+00:00"
    with pytest.raises(ValueError, match="catalyst"):
        load_shadow_case(_write(tmp_path, payload))


def test_rejects_future_outcome_embedded_in_case(tmp_path):
    payload = _payload()
    payload["outcomes"] = {"20d": 0.12}
    with pytest.raises(ValueError, match="outcome"):
        load_shadow_case(_write(tmp_path, payload))


def test_price_implied_expectation_requires_frozen_assumptions(tmp_path):
    payload = _payload()
    payload["market_expectation"]["method"] = "PRICE_IMPLIED"
    payload["market_expectation"]["valuation_assumptions"] = {}
    with pytest.raises(ValueError, match="assumptions"):
        load_shadow_case(_write(tmp_path, payload))


def test_membership_before_theme_effective_date_is_rejected(tmp_path):
    payload = _payload()
    payload["case"]["as_of"] = "2026-08-31T20:00:00+00:00"
    for source in payload["sources"]:
        source["available_at"] = "2026-08-31T19:00:00+00:00"
        source["event_time"] = "2026-08-31T18:00:00+00:00"
    payload["our_expectation"]["as_of"] = payload["case"]["as_of"]
    payload["our_expectation"]["available_at"] = "2026-08-31T19:00:00+00:00"
    payload["market_expectation"]["as_of"] = payload["case"]["as_of"]
    payload["market_expectation"]["available_at"] = "2026-08-31T19:00:00+00:00"
    payload["catalysts"][0]["known_at"] = "2026-08-31T19:00:00+00:00"
    case = load_shadow_case(_write(tmp_path, payload))
    with pytest.raises(ValueError, match="effective"):
        validate_etn_vertical_slice_case(case, load_theme_package(PACKAGE_PATH))
