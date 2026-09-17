"""SAC-SMA parameter groups and absolute search bounds."""

from __future__ import annotations

SAC_SMA_PARAM_GROUPS: dict[str, tuple[str, ...]] = {
    "upper": ("UZTWM", "UZFWM", "UZK", "PCTIM"),
    "lower": ("LZTWM", "LZFSM", "LZFPM", "LZSK", "LZPK"),
    "percolation": ("ZPERC", "REXP"),
    "routing": ("UHK",),
}

ALL_PARAM_GROUPS: tuple[str, ...] = ("upper", "lower", "percolation", "routing")

SAC_SMA_PARAMETER_BOUNDS: dict[str, tuple[float, float]] = {
    "UZTWM": (10.0, 150.0),
    "UZFWM": (10.0, 150.0),
    "UZK": (0.1, 0.7),
    "PCTIM": (0.0, 0.2),
    "LZTWM": (20.0, 400.0),
    "LZFSM": (10.0, 250.0),
    "LZFPM": (20.0, 500.0),
    "LZSK": (0.01, 0.25),
    "LZPK": (0.001, 0.05),
    "ZPERC": (1.0, 80.0),
    "REXP": (1.0, 5.0),
    "UHK": (1.0, 7.0),
}

DEFAULT_SAC_SMA_PARAMS: dict[str, float] = {
    "UZTWM": 50.0,
    "UZFWM": 40.0,
    "UZK": 0.3,
    "PCTIM": 0.01,
    "LZTWM": 120.0,
    "LZFSM": 40.0,
    "LZFPM": 150.0,
    "LZSK": 0.08,
    "LZPK": 0.01,
    "ZPERC": 20.0,
    "REXP": 2.0,
    "UHK": 2.5,
}


def resolve_param_names(groups: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not groups:
        groups = ALL_PARAM_GROUPS
    names: list[str] = []
    seen: set[str] = set()
    for group in groups:
        key = str(group).strip().lower()
        if key not in SAC_SMA_PARAM_GROUPS:
            raise KeyError(f"unknown SAC-SMA param group: {group}")
        for name in SAC_SMA_PARAM_GROUPS[key]:
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
        if key not in SAC_SMA_PARAM_GROUPS:
            raise KeyError(f"unknown SAC-SMA param group: {part}")
        if key not in out:
            out.append(key)
    return tuple(out)
