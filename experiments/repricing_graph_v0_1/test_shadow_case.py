from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from experiments.repricing_graph_v0_1.case_io import load_shadow_case
from experiments.repricing_graph_v0_1.context import build_repricing_context
from experiments.repricing_graph_v0_1.gap import calculate_expectation_gap, ExpectationGap
from experiments.repricing_graph_v0_1.model import EstimateKind, RealityEstimate
from experiments.repricing_graph_v0_1.shadow_case import compile_shadow_repricing_decision

CASE="experiments/repricing_graph_v0_1/cases/ETN_2026Q2_shadow.yaml"


def context():
    idx=pd.bdate_range("2026-06-15",periods=70)
    close=pd.Series(np.linspace(400,440,70),index=idx)
    ohlcv=pd.DataFrame({"Open":close*.995,"High":close*1.01,"Low":close*.99,"Close":close,"Volume":np.linspace(100000,130000,70)},index=idx)
    returns=pd.DataFrame({"ETN":close.pct_change(),"NVT":pd.Series(np.linspace(150,170,70),index=idx).pct_change(),"POWL":pd.Series(np.linspace(180,195,70),index=idx).pct_change()})
    bench=pd.Series(np.linspace(700,770,70),index=idx)
    return build_repricing_context(
        returns=returns,members=["ETN","NVT","POWL"],target="ETN",ohlcv=ohlcv,
        benchmark_close=bench,context_as_of="2026-09-25T23:30:00+00:00",
        market_available_at="2026-09-25T20:00:00+00:00",theme_market_observation_ref="scan:etn",
    )


def positive_case():
    case=load_shadow_case(CASE)
    ours=replace(case.our_expectation, kind=EstimateKind.INTERVAL, point=None, lower=13.8, upper=14.2)
    return replace(case, our_expectation=ours)


def test_real_case_with_gap_straddling_zero_stays_researching():
    case=load_shadow_case(CASE)
    gap=calculate_expectation_gap(case.our_expectation,case.market_expectation)
    decision=compile_shadow_repricing_decision(case=case,gap=gap,context=context(),causal_exposure_validated=True)
    assert decision.status=="RESEARCHING"


def test_missing_gap_stays_researching_even_with_good_tape():
    case=positive_case()
    decision=compile_shadow_repricing_decision(case=case,gap=None,context=context(),causal_exposure_validated=True)
    assert decision.status=="RESEARCHING"


def test_missing_causal_exposure_stays_researching():
    case=positive_case(); gap=calculate_expectation_gap(case.our_expectation,case.market_expectation)
    decision=compile_shadow_repricing_decision(case=case,gap=gap,context=context(),causal_exposure_validated=False)
    assert decision.status=="RESEARCHING"


def test_dominant_contradiction_invalidates():
    case=positive_case(); gap=calculate_expectation_gap(case.our_expectation,case.market_expectation)
    decision=compile_shadow_repricing_decision(case=case,gap=gap,context=context(),causal_exposure_validated=True,dominant_contradiction=True)
    assert decision.status=="INVALIDATED"


def test_complete_positive_gap_and_catalyst_becomes_candidate():
    case=positive_case(); gap=calculate_expectation_gap(case.our_expectation,case.market_expectation)
    decision=compile_shadow_repricing_decision(case=case,gap=gap,context=context(),causal_exposure_validated=True)
    assert gap.lower>0
    assert decision.status=="CANDIDATE"
    assert decision.catalyst.catalyst_id==case.catalysts[0].catalyst_id


def test_tape_cannot_promote_incomplete_case():
    case=positive_case(); ctx=context()
    decision=compile_shadow_repricing_decision(case=case,gap=None,context=ctx,causal_exposure_validated=True)
    assert decision.status=="RESEARCHING"
    assert decision.tape_context==ctx.tape_assessment


def test_frozen_inputs_have_deterministic_hash_and_no_future_outcome_field():
    case=positive_case(); gap=calculate_expectation_gap(case.our_expectation,case.market_expectation); ctx=context()
    a=compile_shadow_repricing_decision(case=case,gap=gap,context=ctx,causal_exposure_validated=True)
    b=compile_shadow_repricing_decision(case=case,gap=gap,context=ctx,causal_exposure_validated=True)
    assert a.case_hash==b.case_hash
    assert not hasattr(a,"realized_20d_return")
    assert not hasattr(a,"outcome")


def test_shadow_case_hash_accepts_numpy_boolean_tape_fields():
    import numpy as np
    from decision_lab.linkage import LinkageResult
    from decision_lab.tape import TapeAssessment
    from experiments.repricing_graph_v0_1.context import RepricingContext

    case = positive_case()
    gap = calculate_expectation_gap(case.our_expectation, case.market_expectation)
    tape = TapeAssessment(
        state="range",
        stage="neutral",
        support=100.0,
        reclaim=101.0,
        pivot=102.0,
        invalidation=99.0,
        higher_low=np.bool_(True),
        new_low_recently=np.bool_(False),
        volume_confirmation=np.bool_(False),
        volatility_contraction=np.bool_(True),
        relative_strength_positive=np.bool_(True),
        reasons=("production numpy booleans",),
    )
    context = RepricingContext(
        theme_market_observation_ref=None,
        target_excluded_linkage=LinkageResult(
            ticker="ETN", control_name="DataCenter_Infra_minus_ETN", window=63,
            correlation=0.5, beta=0.8, r2=0.25, residual_mean=0.0,
            residual_vol=0.01, beta_stability=0.7, decoupling_score=0.3,
            circularity_warning=False, observations=63,
        ),
        tape_assessment=tape,
        context_as_of=case.as_of,
        warnings=(),
    )
    decision = compile_shadow_repricing_decision(
        case=case, gap=gap, context=context, causal_exposure_validated=True
    )
    assert len(decision.case_hash) == 64
