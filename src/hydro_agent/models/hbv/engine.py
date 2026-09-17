"""HBV-light daily engine with a degree-day snowpack (Bergström / Seibert).

Discharge is returned in m³/s after converting runoff depth with basin area.
Forcing columns follow ``required_forcings``: precipitation, temperature, PET.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from .contracts import HbvBasin, HbvScheme
from .param_groups import HBV_PARAMETER_BOUNDS

MODEL_VERSION = "hbv-light-v1-20260916"
MODEL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def runoff_mm_day_to_m3s(runoff_mm_day: float, area_km2: float) -> float:
    return runoff_mm_day * area_km2 * 1000.0 / 86400.0


def _triangle_weights(maxbas: float) -> list[float]:
    n = max(1, int(math.ceil(maxbas)))
    mid = (n + 1) / 2.0
    weights = [max(0.0, 1.0 - abs((i + 1) - mid) / mid) for i in range(n)]
    total = sum(weights)
    if total <= 0:
        return [1.0]
    return [w / total for w in weights]


def simulate(scheme: HbvScheme, basin: HbvBasin, inputs, *, include_warmup: bool = False):
    """Return discharge in m³/s; by default drop the warm-up prefix.

    ``inputs`` is shaped ``(n_days, 1, 3)`` with precipitation (mm), temperature (°C)
    and PET (mm).
    """

    import numpy as np

    p = scheme.parameters
    tt = float(p["TT"])
    cfmax = float(p["CFMAX"])
    cfr = float(p["CFR"])
    cwh = float(p["CWH"])
    fc = float(p["FC"])
    beta = float(p["BETA"])
    lp = float(p["LP"])
    k0 = float(p["K0"])
    k1 = float(p["K1"])
    k2 = float(p["K2"])
    perc = float(p["PERC"])
    weights = _triangle_weights(float(p["MAXBAS"]))
    delay = [0.0] * len(weights)

    snow = 0.0
    liquid = 0.0
    soil = 0.3 * fc
    suz = 0.0
    slz = 0.0
    discharges: list[float] = []

    for row in inputs:
        precip = float(row[0, 0])
        temp = float(row[0, 1])
        pet = float(row[0, 2])
        if precip < 0 or pet < 0 or not np.isfinite([precip, pet, temp]).all():
            raise ValueError("invalid HBV forcing")

        rain = 0.0
        if temp < tt:
            snow += precip
            freeze = min(liquid, cfr * cfmax * (tt - temp))
            snow += freeze
            liquid -= freeze
        else:
            rain = precip
            melt = min(snow, cfmax * (temp - tt))
            snow -= melt
            liquid += melt
            if snow > 0:
                liquid += rain
                rain = 0.0
            hold = cwh * snow
            if liquid > hold:
                rain += liquid - hold
                liquid = hold

        wet = max(0.0, rain)
        recharge = wet * min(1.0, (soil / fc) ** beta) if fc > 0 else wet
        soil = min(fc, max(0.0, soil + wet - recharge))
        aet = pet * min(1.0, soil / max(lp * fc, 1e-6))
        soil = max(0.0, soil - aet)

        suz += recharge
        perc_flow = min(suz, perc)
        suz -= perc_flow
        slz += perc_flow
        q0 = k0 * suz
        q1 = k1 * suz
        suz = max(0.0, suz - q0 - q1)
        q2 = k2 * slz
        slz = max(0.0, slz - q2)
        runoff = max(0.0, q0 + q1 + q2)

        for i in range(len(delay) - 1):
            delay[i] = delay[i + 1] + weights[i] * runoff
        delay[-1] = weights[-1] * runoff
        routed = max(0.0, delay[0])
        discharges.append(runoff_mm_day_to_m3s(float(routed), basin.area_km2))

    values = np.asarray(discharges, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("invalid HBV numerical result")
    if include_warmup:
        return values
    return values[scheme.warmup_days :]


def load_param_ranges() -> dict[str, tuple[float, float]]:
    return {name: tuple(bounds) for name, bounds in HBV_PARAMETER_BOUNDS.items()}
