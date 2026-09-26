from dataclasses import fields
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from decision_lab.tape import assess_tape_state
from decision_lab.themes import load_theme_package
from experiments.repricing_graph_v0_1.case_io import load_shadow_case
from experiments.repricing_graph_v0_1.context import (
    RepricingContext,
    build_repricing_context,
)


CASE = Path("experiments/repricing_graph_v0_1/cases/ETN_2026Q2_shadow.yaml")
THEME = Path("config/themes/datacenter_infra.yaml")


def _market_inputs(perfect=False):
    idx = pd.bdate_range("2026-06-15", periods=74)
    base = pd.Series(np.linspace(0.001, 0.004, len(idx)), index=idx)
    if perfect:
        returns = pd.DataFrame({"ETN": base, "NVT": base, "POWL": base})
    else:
        returns = pd.DataFrame(
            {
                "ETN": base + 0.0005 * np.sin(np.arange(len(idx))),
                "NVT": base * 0.8,
                "POWL": base * 1.2,
            }
        )

    close = 300 * (1 + returns["ETN"]).cumprod()
    ohlcv = pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]),
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.linspace(1_000_000, 1_400_000, len(idx)),
        },
        index=idx,
    )
    benchmark = 100 * (1 + pd.Series(0.0015, index=idx)).cumprod()
    return returns, ohlcv, benchmark


def _build(**overrides):
    case = load_shadow_case(CASE)
    package = load_theme_package(THEME)
    returns, ohlcv, benchmark = _market_inputs()
    args = dict(
        case=case,
        package=package,
        returns=returns,
        ohlcv=ohlcv,
        benchmark_close=benchmark,
        market_available_at="2026-09-25T21:00:00+00:00",
        theme_market_observation_ref="market-observation:ETN-shadow",
    )
    args.update(overrides)
    return case, build_repricing_context(**args)


def test_context_mechanically_excludes_target_from_control():
    _, context = _build()
    assert isinstance(context, RepricingContext)
    assert "ETN" not in context.target_excluded_members
    assert set(context.target_excluded_members) == {"NVT", "POWL"}
    assert context.target_excluded_linkage.control_name == "control_minus_ETN"


def test_linkage_is_diagnostic_not_expected_alpha():
    _, context = _build()
    names = {field.name for field in fields(context)}
    assert "expected_alpha" not in names
    assert "economic_exposure" not in names
    assert context.target_excluded_linkage.ticker == "ETN"


def test_existing_tape_output_is_preserved_unchanged():
    case = load_shadow_case(CASE)
    package = load_theme_package(THEME)
    returns, ohlcv, benchmark = _market_inputs()
    expected = assess_tape_state(ohlcv, benchmark_close=benchmark)
    context = build_repricing_context(
        case=case,
        package=package,
        returns=returns,
        ohlcv=ohlcv,
        benchmark_close=benchmark,
        market_available_at="2026-09-25T21:00:00+00:00",
        theme_market_observation_ref="market-observation:ETN-shadow",
    )
    assert context.tape_assessment == expected


def test_missing_market_observation_is_warning_not_fabricated_score():
    _, context = _build(theme_market_observation_ref=None)
    assert "theme market observation unavailable" in context.warnings
    assert context.theme_market_observation_ref is None


def test_context_rejects_market_data_available_after_case_as_of():
    with pytest.raises(ValueError, match="available_at"):
        _build(market_available_at="2026-09-27T00:00:00+00:00")


def test_perfect_statistical_linkage_does_not_create_causal_exposure():
    case = load_shadow_case(CASE)
    package = load_theme_package(THEME)
    returns, ohlcv, benchmark = _market_inputs(perfect=True)
    context = build_repricing_context(
        case=case,
        package=package,
        returns=returns,
        ohlcv=ohlcv,
        benchmark_close=benchmark,
        market_available_at="2026-09-25T21:00:00+00:00",
        theme_market_observation_ref=None,
    )
    assert context.target_excluded_linkage.circularity_warning is True
    assert case.status == "RESEARCHING"
    assert not hasattr(context, "causal_exposure")


def test_context_rejects_target_missing_from_return_frame():
    case = load_shadow_case(CASE)
    package = load_theme_package(THEME)
    returns, ohlcv, benchmark = _market_inputs()
    with pytest.raises(ValueError, match="target"):
        build_repricing_context(
            case=case,
            package=package,
            returns=returns.drop(columns=["ETN"]),
            ohlcv=ohlcv,
            benchmark_close=benchmark,
            market_available_at="2026-09-25T21:00:00+00:00",
            theme_market_observation_ref=None,
        )
