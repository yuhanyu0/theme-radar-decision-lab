from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases"


def test_real_20260925_shadow_decision_is_frozen_and_non_bullish():
    artifact = CASES / "ETN_20260925_shadow_decision.json"
    assert artifact.exists(), "real 2026-09-25 shadow decision artifact is not frozen"
    payload = json.loads(artifact.read_text(encoding="utf-8"))

    assert payload["ticker"] == "ETN"
    assert payload["theme_id"] == "DataCenter_Infra"
    assert payload["as_of"] == "2026-09-25T23:30:00+00:00"
    assert payload["status"] == "RESEARCHING"
    assert payload["expectation_gap"]["kind"] == "INTERVAL"
    assert payload["expectation_gap"]["lower"] < 0 < payload["expectation_gap"]["upper"]
    assert payload["tape_context"]["state"]
    assert payload["tape_context"]["stage"]
    assert payload["target_excluded_linkage"]["ticker"] == "ETN"
    assert payload["target_excluded_linkage"]["control_name"] == "DataCenter_Infra_minus_ETN"
    assert payload["target_excluded_linkage"]["observations"] >= 63
    assert payload["market_data_provenance"]["feed"] == "IEX"
    assert payload["market_data_provenance"]["last_session"] == "2026-09-25"
    assert "future_outcomes" not in payload
    assert payload["case_hash"]
