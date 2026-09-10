from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .universe import ThemeUniverse


@dataclass(frozen=True)
class ThemeControls:
    target: str
    layer_name: str
    layer_control_name: str | None
    layer_control: pd.Series | None
    composite_control_name: str
    composite_control: pd.Series
    included_layers: tuple[str, ...]
    warnings: tuple[str, ...]


def _equal_weight(frame: pd.DataFrame, name: str) -> pd.Series:
    if frame.empty:
        raise ValueError("cannot build control from an empty frame")
    return frame.mean(axis=1, skipna=True).rename(name)


def build_layered_leave_one_out_controls(
    returns: pd.DataFrame,
    universe: ThemeUniverse,
    target: str,
    *,
    min_members_per_layer: int = 2,
) -> ThemeControls:
    """Build subtheme and layer-equal composite controls, excluding `target` everywhere.

    The composite gives each *layer* equal influence, then equal-weights surviving
    members inside a layer. This prevents a large/high-beta layer from mechanically
    defining the whole theme. Layers with fewer than `min_members_per_layer`
    surviving members are excluded from the composite and surfaced as warnings.
    """
    target = target.upper()
    if target not in universe.candidates:
        raise ValueError(f"target {target} is not in the dynamic universe")

    available_columns = {str(c).upper() for c in returns.columns}
    layer_name = universe.candidates[target].layer
    layer_series: dict[str, pd.Series] = {}
    warnings: list[str] = []

    for layer in universe.layers:
        members = [
            c.ticker.upper()
            for c in universe.by_layer(layer)
            if c.ticker.upper() != target and c.ticker.upper() in available_columns
        ]
        if len(members) < min_members_per_layer:
            warnings.append(
                f"layer {layer} excluded: only {len(members)} non-target members available"
            )
            continue
        name = f"{universe.theme}:{layer}:minus_{target}"
        layer_series[layer] = _equal_weight(returns[members], name)

    if len(layer_series) < 2:
        raise ValueError("composite control requires at least two valid non-target layers")

    composite_frame = pd.concat(layer_series.values(), axis=1)
    composite_name = f"{universe.theme}:layer_equal_composite:minus_{target}"
    composite = _equal_weight(composite_frame, composite_name)

    if layer_name in layer_series:
        layer_control_name = layer_series[layer_name].name
        layer_control = layer_series[layer_name]
    else:
        layer_control_name = None
        layer_control = None
        warnings.append(
            f"target layer {layer_name} has no robust leave-one-out layer control; use composite"
        )

    return ThemeControls(
        target=target,
        layer_name=layer_name,
        layer_control_name=layer_control_name,
        layer_control=layer_control,
        composite_control_name=composite_name,
        composite_control=composite,
        included_layers=tuple(layer_series.keys()),
        warnings=tuple(warnings),
    )
