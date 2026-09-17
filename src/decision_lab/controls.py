from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .universe import Candidate, ThemeUniverse


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


def _align_effective_timestamp(value: str, index: pd.DatetimeIndex) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if index.tz is None and timestamp.tz is not None:
        return timestamp.tz_convert("UTC").tz_localize(None)
    if index.tz is not None and timestamp.tz is None:
        return timestamp.tz_localize(index.tz)
    if index.tz is not None and timestamp.tz is not None:
        return timestamp.tz_convert(index.tz)
    return timestamp


def _effective_member_series(
    returns: pd.DataFrame,
    candidate: Candidate,
) -> pd.Series:
    symbol = candidate.ticker.upper()
    series = returns[symbol].copy()
    has_effective_window = candidate.effective_from is not None or candidate.effective_to is not None
    if not has_effective_window and candidate.membership_state != "retired":
        return series.rename(symbol)
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise TypeError("effective-dated controls require a DatetimeIndex")

    mask = pd.Series(True, index=returns.index)
    if candidate.effective_from is not None:
        start = _align_effective_timestamp(candidate.effective_from, returns.index)
        mask &= returns.index >= start
    if candidate.effective_to is not None:
        end = _align_effective_timestamp(candidate.effective_to, returns.index)
        mask &= returns.index < end
    elif candidate.membership_state == "retired":
        mask &= False
    return series.where(mask).rename(symbol)


def build_layered_leave_one_out_controls(
    returns: pd.DataFrame,
    universe: ThemeUniverse,
    target: str,
    *,
    min_members_per_layer: int = 2,
) -> ThemeControls:
    """Build target-excluded, effective-dated layer-equal theme controls.

    Each layer receives equal influence after equal-weighting members that were actually
    effective on each observation date. Future members are masked before `effective_from`
    and retired members with an explicit `effective_to` disappear from that date forward.
    This prevents current universe membership from leaking backward into historical
    linkage windows. The target is excluded everywhere.
    """
    target = target.upper()
    if target not in universe.candidates:
        raise ValueError(f"target {target} is not in the dynamic universe")

    available_columns = {str(c).upper() for c in returns.columns}
    layer_name = universe.candidates[target].layer
    layer_series: dict[str, pd.Series] = {}
    warnings: list[str] = []

    for layer in universe.layers:
        candidates = [
            candidate
            for candidate in universe.candidates.values()
            if candidate.layer == layer
            and candidate.ticker.upper() != target
            and candidate.ticker.upper() in available_columns
        ]
        if len(candidates) < min_members_per_layer:
            warnings.append(
                f"layer {layer} excluded: only {len(candidates)} non-target members available"
            )
            continue

        member_frame = pd.concat(
            [_effective_member_series(returns, candidate) for candidate in candidates],
            axis=1,
        )
        valid_members = member_frame.notna().sum(axis=1)
        name = f"{universe.theme}:{layer}:minus_{target}"
        control = _equal_weight(member_frame, name).where(
            valid_members >= min_members_per_layer
        )
        if not control.notna().any():
            warnings.append(
                f"layer {layer} excluded: no dates have {min_members_per_layer} effective members"
            )
            continue
        if control.isna().any():
            warnings.append(
                f"layer {layer} has dates with insufficient effective non-target members"
            )
        layer_series[layer] = control

    if len(layer_series) < 2:
        raise ValueError("composite control requires at least two valid non-target layers")

    composite_frame = pd.concat(layer_series.values(), axis=1)
    valid_layers = composite_frame.notna().sum(axis=1)
    composite_name = f"{universe.theme}:layer_equal_composite:minus_{target}"
    composite = _equal_weight(composite_frame, composite_name).where(valid_layers >= 2)

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
