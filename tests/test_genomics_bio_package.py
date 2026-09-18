from pathlib import Path

from decision_lab.themes import load_theme_package

ROOT = Path(__file__).resolve().parents[1]


def test_genomics_bio_loads_as_generic_theme_package_without_datacenter_thresholds():
    package = load_theme_package(ROOT / "config/themes/genomics_bio.yaml")

    assert package.definition.theme_id == "Genomics_Bio"
    assert package.definition.lifecycle_state.value == "strengthening"
    assert package.evidence_adapter == "biotech_clinical"

    assert package.theme_key_policy.minimum_flow is None
    assert package.theme_key_policy.probe_structure is None
    assert package.theme_key_policy.full_structure is None
    assert package.theme_key_policy.structure_percentile_min == 0.80
    assert package.theme_key_policy.minimum_valid_sessions == 3

    assert set(package.universe.layers) == {
        "genome_editing_therapeutics",
        "gene_therapy_delivery",
        "sequencing_enabling_tools",
        "genomic_diagnostics",
    }
    assert {"CRSP", "BEAM", "NTLA", "ILMN", "PACB", "NTRA"} <= set(
        package.universe.symbols()
    )


def test_genomics_seed_members_are_not_promoted_to_validated_by_configuration():
    package = load_theme_package(ROOT / "config/themes/genomics_bio.yaml")
    assert package.universe.candidates
    assert all(
        candidate.membership_state in {"discovery", "provisional"}
        for candidate in package.universe.candidates.values()
    )
