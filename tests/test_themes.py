from decision_lab.themes import (
    ThemeCalibrationState,
    ThemeDefinition,
    ThemeKeyPolicy,
    ThemeLifecycleState,
    ThemeRegistry,
)


def test_registry_resolves_alias_and_preserves_historical_versions():
    registry = ThemeRegistry()
    v1 = ThemeDefinition(
        theme_id="Grid_Modernization",
        display_name="Grid Modernization",
        aliases=("Grid",),
        lifecycle_state=ThemeLifecycleState.FORMING,
        effective_from="2026-01-01",
        version="1",
    )
    v2 = ThemeDefinition(
        theme_id="Grid_Modernization",
        display_name="Grid Modernization",
        aliases=("Grid",),
        lifecycle_state=ThemeLifecycleState.STRENGTHENING,
        effective_from="2026-06-01",
        version="2",
    )
    registry.register(v1)
    registry.register(v2)

    assert registry.resolve("Grid", as_of="2026-03-01").version == "1"
    assert registry.resolve("Grid_Modernization", as_of="2026-07-01").version == "2"
    assert registry.latest("Grid").lifecycle_state is ThemeLifecycleState.STRENGTHENING


def test_alias_collision_registration_is_atomic():
    registry = ThemeRegistry()
    registry.register(
        ThemeDefinition(
            theme_id="Theme_A",
            display_name="Theme A",
            aliases=("Shared",),
            version="1",
        )
    )
    conflicting = ThemeDefinition(
        theme_id="Theme_B",
        display_name="Theme B",
        aliases=("Shared",),
        version="1",
    )

    try:
        registry.register(conflicting)
    except ValueError as exc:
        assert "alias collision" in str(exc).lower()
    else:
        raise AssertionError("alias collision must be rejected")

    assert registry.latest("Shared").theme_id == "Theme_A"
    try:
        registry.latest("Theme_B")
    except KeyError:
        pass
    else:
        raise AssertionError("failed registration must not partially mutate registry")


def test_parent_child_relationships_reject_self_parent():
    definition = ThemeDefinition(
        theme_id="Defense_Autonomy",
        display_name="Defense Autonomy",
        parent_theme_id="Defense_Autonomy",
        version="1",
    )
    try:
        definition.validate()
    except ValueError as exc:
        assert "parent" in str(exc).lower()
    else:
        raise AssertionError("self-parent theme must be rejected")


def test_global_theme_key_policy_has_no_datacenter_thresholds():
    policy = ThemeKeyPolicy()
    assert policy.calibration_state is ThemeCalibrationState.UNCALIBRATED
    assert policy.minimum_flow is None
    assert policy.probe_structure is None
    assert policy.full_structure is None


def test_default_theme_key_policy_is_uncalibrated_and_fails_closed():
    policy = ThemeKeyPolicy()

    result = policy.evaluate(
        flow=1.0,
        structure=1.0,
        valid_sessions=999,
        permission="probe",
        structure_percentile=1.0,
        carry=1.0,
        raw_calibrated_gap=0.0,
    )

    assert policy.calibration_state is ThemeCalibrationState.UNCALIBRATED
    assert not result.satisfied
    assert result.reasons == ("theme key policy uncalibrated",)


def test_operational_policy_without_substantive_gate_fails_closed():
    policy = ThemeKeyPolicy(
        calibration_state=ThemeCalibrationState.OPERATIONAL,
        minimum_valid_sessions=2,
    )

    result = policy.evaluate(
        flow=None,
        structure=None,
        valid_sessions=10,
        permission="probe",
    )

    assert not result.satisfied
    assert result.reasons == ("theme key policy has no substantive evidence gate",)


def test_operational_policy_evaluates_configured_gates_normally():
    policy = ThemeKeyPolicy(
        calibration_state=ThemeCalibrationState.OPERATIONAL,
        minimum_flow=0.50,
        probe_structure=0.08,
        full_structure=0.35,
        minimum_valid_sessions=2,
    )

    assert policy.evaluate(
        flow=0.52,
        structure=0.10,
        valid_sessions=2,
        permission="probe",
    ).satisfied
    assert not policy.evaluate(
        flow=0.49,
        structure=0.10,
        valid_sessions=2,
        permission="probe",
    ).satisfied
    assert policy.evaluate(
        flow=0.52,
        structure=0.36,
        valid_sessions=2,
        permission="full",
    ).satisfied


def test_theme_key_policy_requires_all_configured_inputs():
    policy = ThemeKeyPolicy(
        calibration_state=ThemeCalibrationState.OPERATIONAL,
        minimum_flow=0.50,
        probe_structure=0.08,
        full_structure=0.35,
        minimum_valid_sessions=2,
    )
    assert policy.evaluate(flow=0.52, structure=0.10, valid_sessions=2, permission="probe").satisfied
    assert not policy.evaluate(flow=0.52, structure=None, valid_sessions=2, permission="probe").satisfied
    assert not policy.evaluate(flow=0.52, structure=0.10, valid_sessions=1, permission="probe").satisfied
    assert policy.evaluate(flow=0.52, structure=0.36, valid_sessions=2, permission="full").satisfied


def test_non_operational_string_calibration_state_cannot_bypass_fail_closed():
    policy = ThemeKeyPolicy(
        calibration_state="uncalibrated",
        minimum_flow=0.50,
    )

    result = policy.evaluate(
        flow=1.0,
        structure=None,
        valid_sessions=10,
        permission="probe",
    )

    assert not result.satisfied
    assert result.reasons == ("theme key policy uncalibrated",)


def test_unknown_calibration_state_fails_closed_even_with_satisfied_gate():
    policy = ThemeKeyPolicy(
        calibration_state="typo_state",
        minimum_flow=0.50,
    )

    result = policy.evaluate(
        flow=1.0,
        structure=None,
        valid_sessions=10,
        permission="probe",
    )

    assert not result.satisfied
    assert result.reasons == ("theme key policy uncalibrated",)
