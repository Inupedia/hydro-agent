"""GR4J parameter groups and absolute search bounds."""

from __future__ import annotations

GR4J_PARAM_GROUPS: dict[str, tuple[str, ...]] = {
    "production": ("X1",),
    "exchange": ("X2",),
    "routing": ("X3", "X4"),
}

ALL_PARAM_GROUPS: tuple[str, ...] = ("production", "exchange", "routing")

# Literature-typical absolute bounds (airGR / CEMAGREF practice ranges).
GR4J_PARAMETER_BOUNDS: dict[str, tuple[float, float]] = {
    "X1": (10.0, 2000.0),
    "X2": (-10.0, 5.0),
    "X3": (1.0, 500.0),
    "X4": (0.5, 5.0),
}

DEFAULT_GR4J_PARAMS: dict[str, float] = {
    "X1": 350.0,
    "X2": 0.0,
    "X3": 90.0,
    "X4": 1.7,
}


def resolve_param_names(groups: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not groups:
        groups = ALL_PARAM_GROUPS
    names: list[str] = []
    seen: set[str] = set()
    for group in groups:
        key = str(group).strip().lower()
        if key not in GR4J_PARAM_GROUPS:
            raise KeyError(f"unknown GR4J param group: {group}")
        for name in GR4J_PARAM_GROUPS[key]:
            if name not in seen:
                seen.add(name)
                names.append(name)
    return tuple(names)


def normalize_param_groups(raw) -> tuple[str, ...]:
    if raw is None:
        return ALL_PARAM_GROUPS
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        parts = [str(p).strip() for p in raw if str(p).strip()]
    if not parts:
        return ALL_PARAM_GROUPS
    out: list[str] = []
    for part in parts:
        key = part.lower()
        if key not in GR4J_PARAM_GROUPS:
            raise KeyError(f"unknown GR4J param group: {part}")
        if key not in out:
            out.append(key)
    return tuple(out)
