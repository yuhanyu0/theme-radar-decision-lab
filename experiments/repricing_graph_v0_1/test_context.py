from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from decision_lab.tape import assess_tape_state
from experiments.repricing_graph_v0_1.context import build_repricing_context


def _market_inputs():
    index = pd.date_range("2026-05-01", periods=90, freq="B")
    base = np.linspace(100.0, 125.0, len(index))
    returns = pd.DataFrame(
        {
            "ETN": pd.Series(base * 1.01, index=index).pct_change(),
            "GEV": pd.Series(base * 1.02, index=index).pct_change(),
            "POWL": pd.Series(base * 0.99, index=index).pct_change(),
            "NVT": pd.Series(base * 1.03, index=index).pct_change(),
        },
        index=index,
    ).fillna(0.0)
    close = pd.Series(base * 1.01, index=index)
    ohlcv = pd.DataFrame(
        {
            "Open": close * 0.998,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.linspace(1_000_000, 1_500_000, len(index)),
        },
        index=index,
    )
    benchmark = pd.Series(np.linspace(100.0, 115.0, len(index)), index=index)
    return returns, ohlcv, benchmark


def test_context_excludes_target_from_theme_control():
    returns, ohlcv, benchmark = _market_inputs()
    context = build_repricing_context(
        target="ETN",
        members=["ETN", "GEV", "POWL", "NVT"],
        returns=returns,
        ohlcv=ohlcv,
        benchmark_close=benchmark,
        as_of="2026-09-25T20:00:00+00:00",
        market_data_available_at="2026-09-25T20:00:00+00:00",
        market_observation_ref="obs:datacenter",
        economic_exposure_evidence_refs=("etn_q2_release",),
    )
    assert "ETN" not in context.control_members
    assert set(context.control_members) == {"GEV", "POWL", "NVT"}
    assert context.target_excluded_linkage.control_name == "theme_control_minus_ETN"


def test_tape_is_preserved_as_context_not_alpha():
    returns, ohlcv, benchmark = _market_inputs()
    expected = assess_tape_state(ohlcv, benchmark_close=benchmark)
    context = build_repricing_context(
        target="ETN",
        members=["ETN", "GEV", "POWL", "NVT"],
        returns=returns,
        ohlcv=ohlcv,
        benchmark_close=benchmark,
        as_of="2026-09-25T20:00:00+00:00",
        market_data_available_at="2026-09-25T20:00:00+00:00",
        market_observation_ref="obs:datacenter",
        economic_exposure_evidence_refs=("etn_q2_release",),
    )
    assert context.tape_assessment == expected
    assert not hasattr(context, "expected_alpha")


def test_missing_market_observation_is_warning_not_fabricated_score():
    returns, ohlcv, benchmark = _market_inputs()
    context = build_repricing_context(
        target="ETN",
        members=["ETN", "GEV", "POWL", "NVT"],
        returns=returns,
        ohlcv=ohlcv,
        benchmark_close=benchmark,
        as_of="2026-09-25T20:00:00+00:00",
        market_data_available_at="2026-09-25T20:00:00+00:00",
        market_observation_ref=None,
        economic_exposure_evidence_refs=("etn_q2_release",),
    )
    assert context.theme_market_observation_ref is None
    assert "market observation unavailable" in context.warnings


def test_future_market_data_is_rejected():
    returns, ohlcv, benchmark = _market_inputs()
    with pytest.raises(ValueError, match="available"):
        build_repricing_context(
            target="ETN",
            members=["ETN", "GEV", "POWL", "NVT"],
            returns=returns,
            ohlcv=ohlcv,
            benchmark_close=benchmark,
            as_of="2026-09-25T20:00:00+00:00",
            market_data_available_at="2026-09-26T00:00:00+00:00",
            market_observation_ref=None,
            economic_exposure_evidence_refs=("etn_q2_release",),
        )


def test_statistical_linkage_without_economic_evidence_is_not_causal_proof():
    returns, ohlcv, benchmark = _market_inputs()
    context = build_repricing_context(
        target="ETN",
        members=["ETN", "GEV", "POWL", "NVT"],
        returns=returns,
        ohlcv=ohlcv,
        benchmark_close=benchmark,
        as_of="2026-09-25T20:00:00+00:00",
        market_data_available_at="2026-09-25T20:00:00+00:00",
        market_observation_ref="obs:datacenter",
        economic_exposure_evidence_refs=(),
    )
    assert context.causal_exposure_validated is False
    assert "economic exposure evidence missing" in context.warnings


def test_context_rejects_price_rows_after_case_asof_even_if_batch_timestamp_claims_old():
    returns, ohlcv, benchmark = _market_inputs()
    future_day = pd.Timestamp("2026-09-28")
    returns.loc[future_day] = 0.01
    ohlcv.loc[future_day] = {
        "Open": 130.0,
        "High": 132.0,
        "Low": 129.0,
        "Close": 131.0,
        "Volume": 2_000_000.0,
    }
    benchmark.loc[future_day] = 120.0
    with pytest.raises(ValueError, match="future market rows"):
        build_repricing_context(
            target="ETN",
            members=["ETN", "GEV", "POWL", "NVT"],
            returns=returns,
            ohlcv=ohlcv,
            benchmark_close=benchmark,
            as_of="2026-09-25T20:00:00+00:00",
            market_data_available_at="2026-09-25T20:00:00+00:00",
            market_observation_ref="obs:datacenter",
            economic_exposure_evidence_refs=("etn_q2_release",),
        )
