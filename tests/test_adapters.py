from decision_lab.adapters import (
    CompanyEvidenceInput,
    GenericEvidenceAdapter,
    IndustrialsInfrastructureAdapter,
)


def test_generic_adapter_preserves_raw_facts_and_provenance():
    source = CompanyEvidenceInput(
        ticker="XYZ",
        as_of="2026-09-17",
        raw_facts={"revenue_growth": 0.12, "top_customer_share": 0.30},
        provenance=("sec:xyz-10q",),
    )
    result = GenericEvidenceAdapter().normalize(source)
    assert result.raw_facts == source.raw_facts
    assert result.provenance == ("sec:xyz-10q",)
    assert result.source_coverage == "raw_only"


def test_industrials_adapter_emits_bounded_common_contract():
    source = CompanyEvidenceInput(
        ticker="XYZ",
        as_of="2026-09-17",
        raw_facts={
            "revenue_growth": 0.20,
            "gross_margin": 0.35,
            "backlog_growth": 0.30,
            "order_growth": 0.25,
            "fcf_margin": 0.12,
            "net_debt_to_ebitda": 1.0,
            "top_customer_share": 0.28,
            "guidance_revision": 0.05,
        },
        provenance=("company-ir:q2",),
    )
    result = IndustrialsInfrastructureAdapter().normalize(source)
    assert 0.0 <= result.growth <= 1.0
    assert 0.0 <= result.demand_visibility <= 1.0
    assert 0.0 <= result.cash_generation <= 1.0
    assert 0.0 <= result.balance_sheet_strength <= 1.0
    assert result.customer_concentration == 0.28
    assert result.raw_facts["backlog_growth"] == 0.30
    assert result.source_coverage == "industrials_core"
