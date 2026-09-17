"""Classic multi-tank daily rainfall-runoff engine (Sugawara-style).

Discharge is returned in m³/s after converting runoff depth with basin area.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .contracts import TankBasin, TankScheme
from .param_groups import TANK_PARAMETER_BOUNDS

MODEL_VERSION = "tank-v1-20260916"
MODEL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def runoff_mm_day_to_m3s(runoff_mm_day: float, area_km2: float) -> float:
    return runoff_mm_day * area_km2 * 1000.0 / 86400.0


def simulate(scheme: TankScheme, basin: TankBasin, inputs, *, include_warmup: bool = False):
    """Return discharge in m³/s; by default drop the warm-up prefix.

    ``inputs`` is shaped ``(n_days, 1, 2)`` with precipitation and PET in mm/day.
    """

    import numpy as np

    p = scheme.parameters
    h1 = float(p["H1"])
    a11 = float(p["A11"])
    a12 = float(p["A12"])
    b1 = float(p["B1"])
    h2 = float(p["H2"])
    a2 = float(p["A2"])
    b2 = float(p["B2"])
    a3 = float(p["A3"])
    k = float(p["K"])
    n_res = max(1, min(8, int(round(float(p["N"])))))
    stor = [0.0] * n_res

    s1 = 10.0
    s2 = 10.0
    s3 = 20.0
    discharges: list[float] = []

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

        q_high = a11 * max(s1 - h1, 0.0)
        q_side = a12 * s1
        inf1 = b1 * s1
        take1 = min(s1, q_high + q_side + inf1)
        if take1 > 0 and s1 > 0:
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
        runoff = max(0.0, q_high + q_side + q2 + q3)

        routed = runoff
        for i in range(n_res):
            stor[i] += routed
            outflow = k * stor[i]
            stor[i] = max(0.0, stor[i] - outflow)
            routed = outflow
        discharges.append(runoff_mm_day_to_m3s(float(routed), basin.area_km2))

    values = np.asarray(discharges, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("invalid tank numerical result")
    if include_warmup:
        return values
    return values[scheme.warmup_days :]


def load_param_ranges() -> dict[str, tuple[float, float]]:
    return {name: tuple(bounds) for name, bounds in TANK_PARAMETER_BOUNDS.items()}
