import numpy as np
import pandas as pd
import pytest

from decision_lab.linkage import leave_one_out_control
from experiments.repricing_graph_v0_1.context import build_repricing_context


def data(n=70):
    idx=pd.bdate_range("2026-06-15", periods=n)
    base=np.linspace(100,120,n)
    returns=pd.DataFrame({
        "ETN":pd.Series(base,index=idx).pct_change(),
        "NVT":pd.Series(base*1.01 + np.sin(np.arange(n)),index=idx).pct_change(),
        "POWL":pd.Series(base*.99 + np.cos(np.arange(n)),index=idx).pct_change(),
    })
    close=pd.Series(np.linspace(400,440,n),index=idx)
    ohlcv=pd.DataFrame({
        "Open":close*0.995,"High":close*1.01,"Low":close*0.99,"Close":close,
        "Volume":np.linspace(100000,130000,n),
    },index=idx)
    benchmark=pd.Series(np.linspace(700,770,n),index=idx)
    return returns,ohlcv,benchmark


def test_target_excluded_control_mechanically_excludes_etn():
    returns,_,_=data()
    control=leave_one_out_control(returns,["ETN","NVT","POWL"],"ETN")
    expected=returns[["NVT","POWL"]].dropna(how="all").mean(axis=1,skipna=True)
    pd.testing.assert_series_equal(control.rename(None),expected.rename(None))


def test_context_stores_linkage_as_diagnostic_and_tape_unchanged():
    returns,ohlcv,benchmark=data()
    ctx=build_repricing_context(
        returns=returns,members=["ETN","NVT","POWL"],target="ETN",ohlcv=ohlcv,
        benchmark_close=benchmark,context_as_of="2026-09-25T20:00:00+00:00",
        market_available_at="2026-09-25T20:00:00+00:00",theme_market_observation_ref="scan:123",
    )
    assert ctx.target_excluded_linkage.ticker=="ETN"
    assert ctx.target_excluded_linkage.control_name=="DataCenter_Infra_minus_ETN"
    assert ctx.tape_assessment.state
    assert not hasattr(ctx,"expected_alpha")
    assert not hasattr(ctx,"economic_exposure")


def test_missing_market_observation_yields_warning_not_fabricated_score():
    returns,ohlcv,benchmark=data()
    ctx=build_repricing_context(
        returns=returns,members=["ETN","NVT","POWL"],target="ETN",ohlcv=ohlcv,
        benchmark_close=benchmark,context_as_of="2026-09-25T20:00:00+00:00",
        market_available_at="2026-09-25T20:00:00+00:00",theme_market_observation_ref=None,
    )
    assert "market observation unavailable" in ctx.warnings
    assert ctx.theme_market_observation_ref is None


def test_context_rejects_future_market_data():
    returns,ohlcv,benchmark=data()
    with pytest.raises(ValueError,match="market data.*after"):
        build_repricing_context(
            returns=returns,members=["ETN","NVT","POWL"],target="ETN",ohlcv=ohlcv,
            benchmark_close=benchmark,context_as_of="2026-09-25T20:00:00+00:00",
            market_available_at="2026-09-26T20:00:00+00:00",theme_market_observation_ref=None,
        )


def test_perfect_linkage_does_not_create_causal_exposure():
    returns,ohlcv,benchmark=data()
    # Make target exactly equal to the non-target control.
    returns["ETN"]=returns[["NVT","POWL"]].mean(axis=1)
    ctx=build_repricing_context(
        returns=returns,members=["ETN","NVT","POWL"],target="ETN",ohlcv=ohlcv,
        benchmark_close=benchmark,context_as_of="2026-09-25T20:00:00+00:00",
        market_available_at="2026-09-25T20:00:00+00:00",theme_market_observation_ref=None,
    )
    assert ctx.target_excluded_linkage.correlation is not None
    assert ctx.target_excluded_linkage.correlation > .99
    assert "statistical linkage is diagnostic, not causal exposure" in ctx.warnings
