"""Sugawara-family three-tank daily engine with discrete Nash cascade routing.

Structure (product-fixed, not the unique four-tank Sugawara diagram):
  surface tank → intermediate tank → base tank → N linear Nash reservoirs.

``N`` is an integer cascade length in ``[1, 5]``; continuous optimizer samples are
snapped before evaluation via ``canonicalize_parameters``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .contracts import NASH_N_MAX, NASH_N_MIN, TankBasin, TankScheme
from .param_groups import TANK_PARAMETER_BOUNDS, snap_discrete_parameters

MODEL_VERSION = "tank-3nash-v2-20260917"
MODEL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def runoff_mm_day_to_m3s(runoff_mm_day: float, area_km2: float) -> float:
    return runoff_mm_day * area_km2 * 1000.0 / 86400.0


def m3s_to_runoff_mm_day(discharge_m3s: float, area_km2: float) -> float:
    return discharge_m3s * 86400.0 / (area_km2 * 1000.0)


def nash_length(n_value: float) -> int:
    n = int(round(float(n_value)))
    return max(NASH_N_MIN, min(NASH_N_MAX, n))


def simulate(scheme: TankScheme, basin: TankBasin, inputs, *, include_warmup: bool = False):
    """Return discharge in m³/s; by default drop the warm-up prefix."""

    return _run(
        scheme,
        basin,
        inputs,
        include_warmup=include_warmup,
        collect_diagnostics=False,
    )


def simulate_diagnostics(
    scheme: TankScheme,
    basin: TankBasin,
    inputs,
    *,
    include_warmup: bool = False,
    init_s1: float | None = None,
    init_s2: float | None = None,
    init_s3: float | None = None,
    init_nash: list[float] | None = None,
) -> dict[str, Any]:
    """Return daily diagnostic series in mm/day plus ending state."""

    values, diagnostics, state_end = _run(
        scheme,
        basin,
        inputs,
        include_warmup=include_warmup,
        collect_diagnostics=True,
        init_s1=init_s1,
        init_s2=init_s2,
        init_s3=init_s3,
        init_nash=init_nash,
    )
    area = float(basin.area_km2)
    out = dict(diagnostics)
    out["Qsim"] = __import__("numpy").asarray(
        [m3s_to_runoff_mm_day(float(q), area) for q in values],
        dtype=float,
    )
    out["discharge_m3s"] = values
    out["StateEnd"] = state_end
    return out


def _run(
    scheme: TankScheme,
    basin: TankBasin,
    inputs,
    *,
    include_warmup: bool,
    collect_diagnostics: bool,
    init_s1: float | None = None,
    init_s2: float | None = None,
    init_s3: float | None = None,
    init_nash: list[float] | None = None,
) -> Any:
    import numpy as np

    p = snap_discrete_parameters(scheme.parameters)
    h1 = float(p["H1"])
    a11 = float(p["A11"])
    a12 = float(p["A12"])
    b1 = float(p["B1"])
    h2 = float(p["H2"])
    a2 = float(p["A2"])
    b2 = float(p["B2"])
    a3 = float(p["A3"])
    k = float(p["K"])
    n_res = nash_length(p["N"])
    if init_nash is None:
        stor = [0.0] * n_res
    else:
        stor = [float(v) for v in init_nash]
        if len(stor) != n_res:
            raise ValueError("tank Nash state length mismatch")

    # Default initial storages (mm) for cold start.
    s1 = 10.0 if init_s1 is None else float(init_s1)
    s2 = 10.0 if init_s2 is None else float(init_s2)
    s3 = 20.0 if init_s3 is None else float(init_s3)
    discharges: list[float] = []
    diagnostics: dict[str, list[float]] | None = (
        {
            "S1": [],
            "S2": [],
            "S3": [],
            "Qsurface": [],
            "Qinter": [],
            "Qbase": [],
            "ET": [],
        }
        if collect_diagnostics
        else None
    )

    for row in inputs:
        precip = float(row[0, 0])
        pet = float(row[0, 1])
        if precip < 0 or pet < 0 or not np.isfinite(precip) or not np.isfinite(pet):
            raise ValueError("invalid tank forcing")

        s1 += precip
        et1 = min(s1, pet)
        s1 -= et1
        et2 = min(s2, max(0.0, pet - et1) * 0.5)
        s2 -= et2
        et_total = et1 + et2

        q_high = a11 * max(s1 - h1, 0.0)
        q_side = a12 * s1
        inf1 = b1 * s1
        take1 = min(s1, q_high + q_side + inf1)
        if take1 > 0 and (q_high + q_side + inf1) > 0:
            scale = take1 / (q_high + q_side + inf1)
            q_high *= scale
            q_side *= scale
            inf1 *= scale
        s1 = max(0.0, s1 - take1)

        s2 += inf1
        q2 = a2 * max(s2 - h2, 0.0)
        inf2 = b2 * s2
        take2 = min(s2, q2 + inf2)
        if take2 > 0 and (q2 + inf2) > 0:
            scale = take2 / (q2 + inf2)
            q2 *= scale
            inf2 *= scale
        s2 = max(0.0, s2 - take2)

        s3 += inf2
        q3 = a3 * s3
        s3 = max(0.0, s3 - q3)
        q_surface = q_high + q_side
        runoff = max(0.0, q_surface + q2 + q3)

        routed = runoff
        for i in range(n_res):
            stor[i] += routed
            outflow = k * stor[i]
            stor[i] = max(0.0, stor[i] - outflow)
            routed = outflow
        discharges.append(runoff_mm_day_to_m3s(float(routed), basin.area_km2))

        if diagnostics is not None:
            diagnostics["S1"].append(s1)
            diagnostics["S2"].append(s2)
            diagnostics["S3"].append(s3)
            diagnostics["Qsurface"].append(q_surface)
            diagnostics["Qinter"].append(q2)
            diagnostics["Qbase"].append(q3)
            diagnostics["ET"].append(et_total)

    values = np.asarray(discharges, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("invalid tank numerical result")
    state_end = {
        "s1": float(s1),
        "s2": float(s2),
        "s3": float(s3),
        "nash": list(stor),
        "n": float(n_res),
    }
    if not include_warmup:
        values = values[scheme.warmup_days :]
        if diagnostics is not None:
            diagnostics = {
                key: series[scheme.warmup_days :] for key, series in diagnostics.items()
            }
    if diagnostics is None:
        return values
    return (
        values,
        {key: np.asarray(series, dtype=float) for key, series in diagnostics.items()},
        state_end,
    )


def load_param_ranges() -> dict[str, tuple[float, float]]:
    return {name: tuple(bounds) for name, bounds in TANK_PARAMETER_BOUNDS.items()}
