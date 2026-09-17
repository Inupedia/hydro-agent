"""HBV-light parameter groups and absolute search bounds."""

from __future__ import annotations

HBV_PARAM_GROUPS: dict[str, tuple[str, ...]] = {
    "snow": ("TT", "CFMAX", "SFCF", "CFR", "CWH"),
    "soil": ("FC", "BETA", "LP"),
    "groundwater": ("K0", "K1", "K2", "PERC", "UZL"),
    "routing": ("MAXBAS",),
}

ALL_PARAM_GROUPS: tuple[str, ...] = ("snow", "soil", "groundwater", "routing")

# Ranges guided by Seibert (1997) / Seibert & Vis (2012) via hydromad hbv.ranges().
HBV_PARAMETER_BOUNDS: dict[str, tuple[float, float]] = {
    "TT": (-2.5, 2.5),
    "CFMAX": (1.0, 10.0),
    "SFCF": (0.4, 1.0),
    "CFR": (0.0, 0.1),
    "CWH": (0.0, 0.2),
    "FC": (50.0, 500.0),
    "BETA": (1.0, 6.0),
    "LP": (0.3, 1.0),
    "K0": (0.05, 0.5),
    "K1": (0.01, 0.3),
    "K2": (0.001, 0.1),
    "PERC": (0.0, 3.0),
    "UZL": (0.0, 100.0),
    "MAXBAS": (1.0, 7.0),
}

DEFAULT_HBV_PARAMS: dict[str, float] = {
    "TT": 0.0,
    "CFMAX": 3.0,
    "SFCF": 1.0,
    "CFR": 0.05,
    "CWH": 0.1,
    "FC": 250.0,
    "BETA": 2.0,
    "LP": 0.7,
    "K0": 0.2,
    "K1": 0.08,
    "K2": 0.02,
    "PERC": 1.0,
    "UZL": 40.0,
    "MAXBAS": 2.5,
}


def resolve_param_names(groups: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not groups:
        groups = ALL_PARAM_GROUPS
    names: list[str] = []
    seen: set[str] = set()
    for group in groups:
        key = str(group).strip().lower()
        if key not in HBV_PARAM_GROUPS:
            raise KeyError(f"unknown HBV param group: {group}")
        for name in HBV_PARAM_GROUPS[key]:
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
        if key not in HBV_PARAM_GROUPS:
            raise KeyError(f"unknown HBV param group: {part}")
        if key not in out:
            out.append(key)
    return tuple(out)
