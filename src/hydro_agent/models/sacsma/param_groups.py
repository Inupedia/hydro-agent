"""SAC-SMA parameter groups and absolute search bounds (official 16-parameter set)."""

from __future__ import annotations

# Groups follow the NOAA-OWP SAC-SMA process structure. ``routing`` maps to the
# official recession/timing parameters (UZK, LZSK, LZPK).  The repo-level
# triangular-UH base (HOURS) is a fixed scheme routing config, not part of the
# official 16-parameter calibration universe.
SAC_SMA_PARAM_GROUPS: dict[str, tuple[str, ...]] = {
    "upper": ("UZTWM", "UZFWM", "UZK", "PCTIM", "ADIMP"),
    "lower": ("LZTWM", "LZFSM", "LZFPM", "LZSK", "LZPK"),
    "tension": ("LZTWM", "RSERV"),
    "percolation": ("ZPERC", "REXP", "PFREE", "RSERV"),
    "evap": ("UZTWM", "UZFWM", "RIVA", "RSERV"),
    "runoff": ("PCTIM", "ADIMP", "LZFSM", "LZFPM"),
    "baseflow": ("LZPK", "LZSK", "SIDE"),
    "routing": ("UZK", "LZSK", "LZPK"),
}

# The default/full calibration universe covers all 16 official parameters.
FULL_PARAM_GROUPS: tuple[str, ...] = (
    "upper",
    "lower",
    "percolation",
    "routing",
    "evap",
    "baseflow",
)
ALL_PARAM_GROUPS: tuple[str, ...] = FULL_PARAM_GROUPS

# Literature-typical SAC-SMA absolute ranges (NOAA-OWP/HEC conventions) for the
# official 16 parameters.  HOURS is kept out of this calibration universe; it is
# a fixed scheme-level triangular-UH routing config (DEFAULT_SAC_SMA_ROUTING).
SAC_SMA_PARAMETER_BOUNDS: dict[str, tuple[float, float]] = {
    "UZTWM": (1.0, 150.0),
    "UZFWM": (1.0, 150.0),
    "UZK": (0.1, 0.5),
    "PCTIM": (0.0, 0.1),
    "ADIMP": (0.0, 0.4),
    "RIVA": (0.0, 0.1),
    "ZPERC": (1.0, 250.0),
    "REXP": (1.0, 3.0),
    "LZTWM": (5.0, 400.0),
    "LZFSM": (5.0, 300.0),
    "LZFPM": (5.0, 500.0),
    "LZSK": (0.01, 0.35),
    "LZPK": (0.0001, 0.05),
    "PFREE": (0.0, 0.6),
    "SIDE": (0.0, 0.5),
    "RSERV": (0.0, 0.4),
}

SAC_SMA_ROUTING_BOUNDS: dict[str, tuple[float, float]] = {"HOURS": (0.0, 24.0)}

DEFAULT_SAC_SMA_PARAMS: dict[str, float] = {
    "UZTWM": 50.0,
    "UZFWM": 40.0,
    "UZK": 0.3,
    "PCTIM": 0.01,
    "ADIMP": 0.15,
    "RIVA": 0.02,
    "ZPERC": 20.0,
    "REXP": 2.0,
    "LZTWM": 120.0,
    "LZFSM": 40.0,
    "LZFPM": 150.0,
    "LZSK": 0.08,
    "LZPK": 0.01,
    "PFREE": 0.3,
    "SIDE": 0.1,
    "RSERV": 0.3,
}
DEFAULT_SAC_SMA_ROUTING: dict[str, float] = {"HOURS": 4.0}


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
