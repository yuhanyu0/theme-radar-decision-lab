from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from decision_lab.themes import ThemeDefinition, ThemePackage
from decision_lab.universe import Candidate, ThemeLayer, ThemeUniverse
from experiments.repricing_graph_v0_1.case_io import (
    load_shadow_case,
    validate_etn_vertical_slice_case,
    validate_point_in_time_case,
)
from experiments.repricing_graph_v0_1.model import MarketExpectationMethod

CASE=Path(__file__).parent / "cases" / "ETN_2026Q2_shadow.yaml"


def package(effective_from="2026-09-01"):
    u=ThemeUniverse(
        theme="DataCenter_Infra",
        layers={"electrical_switchgear":ThemeLayer("electrical_switchgear")},
        candidates={
            "ETN":Candidate(
                ticker="ETN", theme="DataCenter_Infra", layer="electrical_switchgear",
                membership_state="discovery", expression_role="quality_alpha",
                provenance=("seed",),
            )
        },
        version="0.2-public-seed",
    )
    return ThemePackage(
        definition=ThemeDefinition("DataCenter_Infra", effective_from=effective_from),
        universe=u,
        version="1.0",
    )


def mutate(tmp_path, fn):
    p=yaml.safe_load(CASE.read_text())
    fn(p)
    out=tmp_path/"case.yaml"
    out.write_text(yaml.safe_dump(p, sort_keys=False))
    return out


def test_real_shadow_case_loads_and_is_etn_vertical_slice():
    case=load_shadow_case(CASE)
    validate_point_in_time_case(case)
    validate_etn_vertical_slice_case(case, package())
    assert case.ticker=="ETN"
    assert case.theme_id=="DataCenter_Infra"
    assert case.primary_fundamental_variable=="ETN_FY2026_ADJUSTED_EPS"
    assert case.market_expectation.method is MarketExpectationMethod.SELL_SIDE_CONSENSUS
    assert case.market_expectation.point==pytest.approx(13.54)
    assert case.our_expectation.lower==pytest.approx(13.40)
    assert case.our_expectation.upper==pytest.approx(13.60)
    assert len(case.catalysts)==1
    assert case.catalysts[0].status=="ESTIMATED_WINDOW"


def test_profile_rejects_wrong_ticker(tmp_path):
    p=mutate(tmp_path, lambda x:x["case"].__setitem__("ticker","VRT"))
    case=load_shadow_case(p)
    with pytest.raises(ValueError, match="ETN"):
        validate_etn_vertical_slice_case(case, package())


def test_profile_rejects_wrong_layer(tmp_path):
    p=mutate(tmp_path, lambda x:x["case"].__setitem__("layer","thermal_liquid_cooling"))
    case=load_shadow_case(p)
    with pytest.raises(ValueError, match="electrical_switchgear"):
        validate_etn_vertical_slice_case(case, package())


def test_evidence_available_after_case_asof_is_rejected(tmp_path):
    def f(x): x["sources"][0]["available_at"]="2026-09-26T00:00:00+00:00"
    with pytest.raises(ValueError, match="available after"):
        load_shadow_case(mutate(tmp_path,f))


def test_missing_source_provenance_is_rejected(tmp_path):
    def f(x): x["sources"][0]["url"]=""
    with pytest.raises(ValueError, match="source provenance"):
        load_shadow_case(mutate(tmp_path,f))


def test_current_consensus_without_historical_availability_is_rejected(tmp_path):
    def f(x):
        for s in x["sources"]:
            if s["source_id"]=="zacks_consensus_20260922": s["available_at"]=""
    with pytest.raises(ValueError, match="available_at"):
        load_shadow_case(mutate(tmp_path,f))


def test_management_guidance_cannot_be_labeled_sell_side_consensus(tmp_path):
    def f(x):
        x["market_expectation"]["source_ref"]="eaton_q2_2026_guidance"
        x["market_expectation"]["method"]="SELL_SIDE_CONSENSUS"
    with pytest.raises(ValueError, match="source role"):
        load_shadow_case(mutate(tmp_path,f))


def test_catalyst_known_after_case_asof_is_rejected(tmp_path):
    def f(x): x["catalyst"]["known_at"]="2026-09-26T00:00:00+00:00"
    with pytest.raises(ValueError, match="catalyst.*hindsight"):
        load_shadow_case(mutate(tmp_path,f))


def test_theme_effective_date_is_enforced():
    case=load_shadow_case(CASE)
    with pytest.raises(ValueError, match="Theme.*effective"):
        validate_etn_vertical_slice_case(case, package(effective_from="2026-10-01"))


def test_future_outcome_fields_are_forbidden_in_case_input(tmp_path):
    def f(x): x["case"]["realized_20d_return"]=0.25
    with pytest.raises(ValueError, match="future outcome"):
        load_shadow_case(mutate(tmp_path,f))


def test_price_implied_expectation_requires_frozen_valuation_assumptions(tmp_path):
    def f(x):
        x["market_expectation"]["method"]="PRICE_IMPLIED"
        x["market_expectation"]["valuation_assumptions"]=[]
        x["market_expectation"]["source_ref"]="market_price_20260925"
    with pytest.raises(ValueError, match="valuation assumptions"):
        load_shadow_case(mutate(tmp_path,f))
