from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from experiments.repricing_graph_v0_1.case_io import load_shadow_case
from experiments.repricing_graph_v0_1.context import RepricingContext
from experiments.repricing_graph_v0_1.evaluate import (
    Ablation,
    evaluate_shadow_case,
    run_ablation,
)
from experiments.repricing_graph_v0_1.gap import calculate_expectation_gap
from experiments.repricing_graph_v0_1.shadow_case import compile_shadow_repricing_decision
from decision_lab.linkage import LinkageResult
from decision_lab.tape import TapeAssessment

CASE="experiments/repricing_graph_v0_1/cases/ETN_2026Q2_shadow.yaml"


def decision():
    case=load_shadow_case(CASE)
    gap=calculate_expectation_gap(case.our_expectation,case.market_expectation)
    linkage=LinkageResult("ETN","ctrl",63,.5,.8,.25,0,.02,.5,.3,False,63)
    tape=TapeAssessment("range","neutral",400,430,445,390,False,False,False,False,True,("x",))
    ctx=RepricingContext("scan:1",linkage,tape,case.as_of,("statistical linkage is diagnostic, not causal exposure",))
    return compile_shadow_repricing_decision(case=case,gap=gap,context=ctx,causal_exposure_validated=True)


def series(n=90, start="2026-09-25", base=100.0, drift=.001):
    idx=pd.bdate_range(start,periods=n+1)
    vals=base*np.cumprod(np.r_[1.0,np.repeat(1+drift,n)])
    return pd.Series(vals,index=idx)


def test_evaluation_rejects_insufficient_60d_future_sessions():
    d=decision(); close=series(30)
    with pytest.raises(ValueError,match="60d"):
        evaluate_shadow_case(decision=d,close=close,spy_close=close*.9,sector_close=close*.8,theme_control_close=close*.7)


def test_evaluation_is_immutable_and_reports_20d_60d_mfe_mae_and_relative_returns():
    d=decision(); before=d.case_hash
    close=series(70,base=100,drift=.002)
    spy=series(70,base=200,drift=.001)
    sector=series(70,base=150,drift=.0012)
    theme=series(70,base=120,drift=.0015)
    out=evaluate_shadow_case(decision=d,close=close,spy_close=spy,sector_close=sector,theme_control_close=theme)
    assert d.case_hash==before
    assert set(out.horizons)=={"20d","60d"}
    for h in ("20d","60d"):
        row=out.horizons[h]
        assert row["return"] is not None
        assert row["spy_excess_return"] is not None
        assert row["sector_excess_return"] is not None
        assert row["theme_excess_return"] is not None
        assert row["mfe"] is not None and row["mae"] is not None
    assert out.source_case_hash==d.case_hash


def test_all_required_ablations_have_exact_provenance():
    d=decision()
    for ablation in Ablation:
        rec=run_ablation(d,ablation)
        assert rec.source_case_hash==d.case_hash
        assert rec.ablation is ablation
        assert rec.provenance==(f"ablation:{ablation.value}",)


def test_no_market_expectation_gap_cannot_claim_gap_mechanism():
    rec=run_ablation(decision(),Ablation.NO_MARKET_EXPECTATION_GAP)
    assert rec.expectation_gap_mechanism_present is False


def test_failed_central_ablation_becomes_kill_signal():
    rec=run_ablation(
        decision(),Ablation.NO_MARKET_EXPECTATION_GAP,
        incremental_information_observed=False,
    )
    assert rec.kill_signal is True
    assert "kill" in rec.note.lower()


def test_single_case_never_emits_pvalue_or_alpha_proof():
    close=series(70)
    out=evaluate_shadow_case(decision=decision(),close=close,spy_close=close,sector_close=close,theme_control_close=close)
    assert not hasattr(out,"p_value")
    assert out.alpha_claim_allowed is False
