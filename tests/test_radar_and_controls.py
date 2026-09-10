import numpy as np
import pandas as pd

from decision_lab.controls import build_layered_leave_one_out_controls
from decision_lab.radar import parse_radar_daily_markdown
from decision_lab.universe import ThemeUniverse


RADAR_SAMPLE = """# Theme Radar Daily Brief — 2026-09-10

## Leaders (v1) — W=63
- **Nuclear_Uranium** (0.088)
- Semis (0.070)
- Quantum (0.064)

## Challengers — W=63
**v2:** Rates (0.098), Semis (0.075), Grid_Power (0.060)
**v3:** Crypto (0.092), Metals (0.087), Genomics_Bio (0.081)

## Migration (20D slope) — W=63
**Top risers:**
- axis_Rates: 0.000735
- axis_DataCenter_Infra: 0.000506

**Top fallers:**
- axis_Nuclear_Uranium: -0.000294
- axis_Semis: -0.000449

## Risk line (W=63)
- s1: 0.408
- theta_v1: 0.0186
- v_FR: 178.37
- single_axis_score: 0.516

## Interpretation
**Regime:** `theme_migration`
- Percentiles (W=63 history): vfr_pct=0.41, theta_pct=0.48, s1_pct=0.49, score_pct=0.50.

---
**BUNDLE_ROOT_SHA256:** `79b3cabe1c4d61e7a10224a13e49086ada3bb3f7fe62131f29574047abdb1c25`
"""


def test_parse_radar_daily_markdown_preserves_model_output_as_snapshot():
    snapshot = parse_radar_daily_markdown(RADAR_SAMPLE, source_ref="synthetic")
    assert snapshot.signal_date == "2026-09-10"
    assert snapshot.leaders_v1["Nuclear_Uranium"] == 0.088
    assert snapshot.challengers_v2["Rates"] == 0.098
    assert snapshot.migration_risers["DataCenter_Infra"] == 0.000506
    assert snapshot.migration_fallers["Semis"] == -0.000449
    assert snapshot.risk_percentiles["vfr_pct"] == 0.41
    assert snapshot.regime == "theme_migration"
    assert len(snapshot.snapshot_hash) == 64


def test_layer_equal_composite_excludes_target_everywhere():
    idx = pd.date_range("2026-01-01", periods=100, freq="B")
    rng = np.random.default_rng(7)
    returns = pd.DataFrame(
        {
            "A": rng.normal(0, 0.01, 100),
            "B": rng.normal(0, 0.01, 100),
            "C": rng.normal(0, 0.01, 100),
            "D": rng.normal(0, 0.01, 100),
            "E": rng.normal(0, 0.01, 100),
            "F": rng.normal(0, 0.01, 100),
        },
        index=idx,
    )
    universe = ThemeUniverse.from_records(
        theme="T",
        layers=[
            {"name": "L1", "description": ""},
            {"name": "L2", "description": ""},
        ],
        candidates=[
            {"ticker": "A", "theme": "T", "layer": "L1"},
            {"ticker": "B", "theme": "T", "layer": "L1"},
            {"ticker": "C", "theme": "T", "layer": "L1"},
            {"ticker": "D", "theme": "T", "layer": "L2"},
            {"ticker": "E", "theme": "T", "layer": "L2"},
            {"ticker": "F", "theme": "T", "layer": "L2"},
        ],
    )
    controls = build_layered_leave_one_out_controls(returns, universe, "A")
    expected_l1 = returns[["B", "C"]].mean(axis=1)
    expected_l2 = returns[["D", "E", "F"]].mean(axis=1)
    expected_composite = pd.concat([expected_l1, expected_l2], axis=1).mean(axis=1)
    pd.testing.assert_series_equal(
        controls.composite_control,
        expected_composite.rename("T:layer_equal_composite:minus_A"),
    )
    assert "minus_A" in controls.composite_control_name
