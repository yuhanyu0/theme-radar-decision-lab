import numpy as np
import pandas as pd
import pytest

from decision_lab.hierarchical import HierarchicalControlSpec, hierarchical_linkage


def _series(values, name):
    idx = pd.date_range("2026-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx, name=name)


def test_hierarchical_linkage_estimates_incremental_theme_fit_without_target_leakage():
    rng = np.random.default_rng(42)
    n = 100
    market = rng.normal(0, 0.01, n)
    sector = 0.7 * market + rng.normal(0, 0.006, n)
    industry = 0.5 * sector + rng.normal(0, 0.005, n)
    theme = 0.4 * industry + rng.normal(0, 0.006, n)
    ticker = (
        0.2 * market
        + 0.3 * sector
        + 0.2 * industry
        + 0.9 * theme
        + rng.normal(0, 0.004, n)
    )
    controls = {
        "market": _series(market, "SPY"),
        "sector": _series(sector, "XLK"),
        "industry": _series(industry, "industry"),
        "theme": _series(theme, "theme_minus_X"),
    }
    spec = HierarchicalControlSpec(
        target="X",
        market="market",
        sector="sector",
        industry="industry",
        theme="theme",
        theme_members=("A", "B", "C"),
    )
    result = hierarchical_linkage(_series(ticker, "X"), controls, spec, window=63)
    assert result.status == "ok"
    assert result.theme_beta is not None and result.theme_beta > 0
    assert result.r2 is not None and result.r2 > 0
    assert result.incremental_theme_r2 is not None and result.incremental_theme_r2 > 0
    assert result.circularity_warning is False


def test_hierarchical_control_rejects_target_membership():
    spec = HierarchicalControlSpec(
        target="X",
        market="market",
        theme="theme",
        theme_members=("A", "X"),
    )
    with pytest.raises(ValueError, match="target.*theme control"):
        spec.validate()


def test_identity_like_control_is_rejected():
    values = np.linspace(-0.01, 0.01, 100)
    target = _series(values, "X")
    controls = {
        "market": _series(np.sin(np.arange(100)) / 100, "SPY"),
        "theme": target.rename("bad_theme"),
    }
    spec = HierarchicalControlSpec(
        target="X",
        market="market",
        theme="theme",
        theme_members=("A", "B"),
    )
    with pytest.raises(ValueError, match="identity-like"):
        hierarchical_linkage(target, controls, spec, window=63)


def test_missing_theme_control_returns_coverage_pending():
    values = np.linspace(-0.01, 0.01, 100)
    target = _series(values, "X")
    controls = {"market": _series(np.sin(np.arange(100)) / 100, "SPY")}
    spec = HierarchicalControlSpec(
        target="X",
        market="market",
        theme="theme",
        theme_members=("A", "B"),
    )
    result = hierarchical_linkage(target, controls, spec, window=63)
    assert result.status == "coverage_pending"
    assert result.theme_beta is None
    assert "theme" in result.missing_controls
