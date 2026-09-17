"""Tank-model parameter groups and absolute search bounds."""

from __future__ import annotations

from .contracts import NASH_N_MAX, NASH_N_MIN

TANK_PARAM_GROUPS: dict[str, tuple[str, ...]] = {
    "surface": ("H1", "A11", "A12", "B1"),
    "intermediate": ("H2", "A2", "B2"),
    "base": ("A3",),
    "routing": ("K", "N"),
}

ALL_PARAM_GROUPS: tuple[str, ...] = ("surface", "intermediate", "base", "routing")

# N remains listed with continuous-looking bounds for DDS/SCE sampling, but the
# engine and canonicalize_parameters snap it to an integer in [NASH_N_MIN, NASH_N_MAX].
TANK_PARAMETER_BOUNDS: dict[str, tuple[float, float]] = {
    "H1": (0.0, 80.0),
    "A11": (0.05, 0.5),
    "A12": (0.01, 0.3),
    "B1": (0.05, 0.5),
    "H2": (0.0, 40.0),
    "A2": (0.01, 0.3),
    "B2": (0.01, 0.3),
    "A3": (0.001, 0.1),
    "K": (0.1, 0.8),
    "N": (float(NASH_N_MIN), float(NASH_N_MAX)),
}

DEFAULT_TANK_PARAMS: dict[str, float] = {
    "H1": 15.0,
    "A11": 0.2,
    "A12": 0.1,
    "B1": 0.2,
    "H2": 8.0,
    "A2": 0.08,
    "B2": 0.08,
    "A3": 0.02,
    "K": 0.4,
    "N": 2.0,
}

DISCRETE_PARAMETER_NAMES: tuple[str, ...] = ("N",)


def snap_discrete_parameters(parameters: dict[str, float]) -> dict[str, float]:
    """Return a copy with discrete Tank parameters snapped to legal integers."""

    out = {name: float(value) for name, value in parameters.items()}
    if "N" in out:
        n = int(round(float(out["N"])))
        out["N"] = float(max(NASH_N_MIN, min(NASH_N_MAX, n)))
    return out


def resolve_param_names(groups: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not groups:
        groups = ALL_PARAM_GROUPS
    names: list[str] = []
    seen: set[str] = set()
    for group in groups:
        key = str(group).strip().lower()
        if key not in TANK_PARAM_GROUPS:
            raise KeyError(f"unknown tank param group: {group}")
        for name in TANK_PARAM_GROUPS[key]:
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
        if key not in TANK_PARAM_GROUPS:
            raise KeyError(f"unknown tank param group: {part}")
        if key not in out:
            out.append(key)
    return tuple(out)
