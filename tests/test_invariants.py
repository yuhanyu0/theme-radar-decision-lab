import json

import numpy as np
import pandas as pd
import pytest

from decision_lab.ledger import verify_record, write_immutable_json
from decision_lab.linkage import leave_one_out_control, rolling_linkage
from decision_lab.outcomes import evaluate_forward_outcomes, missed_upside
from decision_lab.playbooks import route_playbooks


def test_leave_one_out_excludes_target():
    idx = pd.date_range("2026-01-01", periods=100, freq="B")
    frame = pd.DataFrame(
        {
            "A": np.linspace(0.0, 0.01, len(idx)),
            "B": np.linspace(0.01, 0.0, len(idx)),
            "C": np.sin(np.arange(len(idx))) / 100,
        },
        index=idx,
    )
    control = leave_one_out_control(frame, ["A", "B", "C"], "A")
    expected = frame[["B", "C"]].mean(axis=1)
    pd.testing.assert_series_equal(control, expected.rename("control_minus_A"))


def test_identity_like_linkage_raises_warning():
    idx = pd.date_range("2026-01-01", periods=100, freq="B")
    x = pd.Series(np.sin(np.arange(100) / 5) / 100, index=idx)
    result = rolling_linkage(x, x.copy(), ticker="X", control_name="bad_control", window=63)
    assert result.circularity_warning is True
    assert result.r2 is not None and result.r2 > 0.99


def test_c_play_does_not_execute_a_falling_knife():
    routed = route_playbooks(
        theme_key=True,
        tape_state="falling_knife",
        tape_stage="B0",
        fundamentals_intact=True,
        world_confidence="high",
    )
    assert routed.action == "BLOCKED"
    assert routed.selected_playbook == "NoTrade"


def test_missing_theme_key_with_valid_b2_is_watch_only_not_blocked():
    routed = route_playbooks(
        theme_key=False,
        tape_state="reclaim",
        tape_stage="B2",
        fundamentals_intact=True,
        world_confidence="low",
    )
    assert routed.selected_playbook == "NoTrade"
    assert routed.action == "WATCH_ONLY"


def test_clean_retest_can_route_to_build_when_theme_key_is_on():
    routed = route_playbooks(
        theme_key=True,
        tape_state="clean_retest",
        tape_stage="B3",
        fundamentals_intact=True,
        world_confidence="high",
    )
    assert routed.selected_playbook == "B"
    assert routed.action == "BUILD_ON_RETEST"


def test_ledger_is_append_only(tmp_path):
    path = tmp_path / "decision.json"
    payload = {"decision_id": "d-001", "action": "WATCH_ONLY"}
    write_immutable_json(path, payload)
    assert verify_record(path)
    with pytest.raises(FileExistsError):
        write_immutable_json(path, payload)

    parsed = json.loads(path.read_text())
    assert parsed["decision_id"] == "d-001"


def test_forward_outcomes_and_missed_upside_are_separate_from_decision():
    idx = pd.date_range("2026-01-01", periods=30, freq="B")
    close = pd.Series(np.linspace(100.0, 130.0, len(idx)), index=idx)
    bench = pd.Series(np.linspace(100.0, 110.0, len(idx)), index=idx)
    outcomes = evaluate_forward_outcomes(
        close=close,
        decision_asof=idx[4],
        benchmark_close=bench,
        horizons=(1, 3, 5, 10, 20),
    )
    assert outcomes["5d"] is not None
    assert outcomes["5d"]["return"] > outcomes["5d"]["benchmark_return"]
    missed = missed_upside(action="WATCH_ONLY", horizons=outcomes, reference_horizon="20d")
    assert missed is not None and missed > 0
    assert missed_upside(action="BUILD_ON_RETEST", horizons=outcomes) == 0.0
