from decision_lab.adapters import BiotechClinicalAdapter, CompanyEvidenceInput


def test_biotech_adapter_preserves_domain_semantics_without_industrials_mislabeling():
    source = CompanyEvidenceInput(
        ticker="XYZ",
        as_of="2026-09-18",
        raw_facts={
            "clinical_phase": "phase_2",
            "endpoint_status": "met",
            "regulatory_state": "IND_active",
            "cash_runway_months": 24,
            "days_to_material_catalyst": 90,
            "platform_validation": 0.70,
            "partnered_economics": 0.60,
        },
        provenance=("sec:xyz-10q", "clinicaltrials:xyz-study"),
    )

    result = BiotechClinicalAdapter().normalize(source)

    assert result.clinical_phase == "phase_2"
    assert result.endpoint_status == "met"
    assert result.regulatory_state == "IND_active"
    assert result.cash_runway_months == 24
    assert result.days_to_material_catalyst == 90
    assert 0.0 <= result.financing_risk <= 1.0
    assert result.platform_validation == 0.70
    assert result.partnered_economics == 0.60

    assert result.demand_visibility is None
    assert result.order_or_contract_visibility is None
    assert result.balance_sheet_strength is None

    assert result.raw_facts == source.raw_facts
    assert result.provenance == source.provenance
    assert result.source_coverage == "biotech_clinical_core"


def test_biotech_adapter_is_part_of_public_market_wide_api():
    import decision_lab

    assert decision_lab.BiotechClinicalAdapter is BiotechClinicalAdapter
    assert decision_lab.BiotechClinicalEvidence is not None
