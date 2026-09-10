"""XAJ parameter groups and phase-specific calibration whitelists."""

from __future__ import annotations

from typing import Literal

ParamGroup = Literal["evap", "runoff", "routing"]
ObjectiveName = Literal["nse", "peak", "composite"]

XAJ_PARAM_GROUPS: dict[ParamGroup, tuple[str, ...]] = {
    "evap": ("K", "UM", "LM", "DM", "C"),
    "runoff": ("B", "IM", "SM", "EX", "KI", "KG"),
    "routing": ("CS", "CI", "CG", "L"),
}

# The coarse groups above remain useful for generic/manual calibration, but the staged
# hydrologist protocol must not let one phase consume another phase's degrees of freedom.
# P2: gross/annual/seasonal water balance; P3: source split + recession; P4: routing.
XAJ_PHASE_PARAM_WHITELISTS: dict[str, tuple[str, ...]] = {
    "water_balance": ("K", "B", "DM"),
    "recession": ("SM", "KI", "KG"),
    "routing_event": ("CS", "CI", "L"),
    "joint": ("K", "B", "DM", "SM", "KI", "KG", "CS", "CI", "L"),
}

ALL_PARAM_GROUPS: tuple[ParamGroup, ...] = ("evap", "runoff", "routing")
ALL_OBJECTIVES: tuple[ObjectiveName, ...] = ("nse", "peak", "composite")


def resolve_param_names(groups: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not groups:
        groups = ALL_PARAM_GROUPS
    names: list[str] = []
    seen: set[str] = set()
    for group in groups:
        key = str(group).strip().lower()
        if key not in XAJ_PARAM_GROUPS:
            raise KeyError(f"unknown param group: {group}")
        for name in XAJ_PARAM_GROUPS[key]:  # type: ignore[index]
            if name not in seen:
                seen.add(name)
                names.append(name)
    return tuple(names)


def resolve_phase_param_names(objective: str) -> tuple[str, ...] | None:
    """Return the hard whitelist for a staged objective, or None for legacy objectives."""

    return XAJ_PHASE_PARAM_WHITELISTS.get(str(objective).strip().lower())


def normalize_param_groups(raw) -> tuple[ParamGroup, ...]:
    if raw is None:
        return ALL_PARAM_GROUPS
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        parts = [str(p).strip() for p in raw if str(p).strip()]
    if not parts:
        return ALL_PARAM_GROUPS
    out: list[ParamGroup] = []
    for part in parts:
        key = part.lower()
        if key not in XAJ_PARAM_GROUPS:
            raise KeyError(f"unknown param group: {part}")
        if key not in out:
            out.append(key)  # type: ignore[arg-type]
    return tuple(out)
