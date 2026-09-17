from decision_lab.themes import (
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
    assert policy.minimum_flow is None
    assert policy.probe_structure is None
    assert policy.full_structure is None


def test_theme_key_policy_requires_all_configured_inputs():
    policy = ThemeKeyPolicy(
        minimum_flow=0.50,
        probe_structure=0.08,
        full_structure=0.35,
        minimum_valid_sessions=2,
    )
    assert policy.evaluate(flow=0.52, structure=0.10, valid_sessions=2, permission="probe").satisfied
    assert not policy.evaluate(flow=0.52, structure=None, valid_sessions=2, permission="probe").satisfied
    assert not policy.evaluate(flow=0.52, structure=0.10, valid_sessions=1, permission="probe").satisfied
    assert policy.evaluate(flow=0.52, structure=0.36, valid_sessions=2, permission="full").satisfied
