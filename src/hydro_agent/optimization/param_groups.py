"""XAJ parameter groups for bounded, agent-selected calibration."""

from __future__ import annotations

from typing import Literal

ParamGroup = Literal["evap", "runoff", "routing"]
ObjectiveName = Literal["nse", "peak", "composite"]

XAJ_PARAM_GROUPS: dict[ParamGroup, tuple[str, ...]] = {
    "evap": ("K", "UM", "LM", "DM", "C"),
    "runoff": ("B", "IM", "SM", "EX", "KI", "KG"),
    "routing": ("CS", "CI", "CG", "L"),
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
