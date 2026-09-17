"""Simplified SAC-SMA daily engine (Burnash structure, reduced parameter set).

Discharge is returned in m³/s after converting runoff depth with basin area.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from .contracts import SacSmaBasin, SacSmaScheme
from .param_groups import SAC_SMA_PARAMETER_BOUNDS

MODEL_VERSION = "sac-sma-v1-20260916"
MODEL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def runoff_mm_day_to_m3s(runoff_mm_day: float, area_km2: float) -> float:
    return runoff_mm_day * area_km2 * 1000.0 / 86400.0


def _triangle_weights(base: float) -> list[float]:
    n = max(1, int(math.ceil(base)))
    mid = (n + 1) / 2.0
    weights = [max(0.0, 1.0 - abs((i + 1) - mid) / mid) for i in range(n)]
    total = sum(weights)
    if total <= 0:
        return [1.0]
    return [w / total for w in weights]


def simulate(scheme: SacSmaScheme, basin: SacSmaBasin, inputs, *, include_warmup: bool = False):
    """Return discharge in m³/s; by default drop the warm-up prefix.

    ``inputs`` is shaped ``(n_days, 1, 2)`` with precipitation and PET in mm/day.
    """

    import numpy as np

    p = scheme.parameters
    uztwm = float(p["UZTWM"])
    uzfwm = float(p["UZFWM"])
    uzk = float(p["UZK"])
    pctim = float(p["PCTIM"])
    lztwm = float(p["LZTWM"])
    lzfsm = float(p["LZFSM"])
    lzfpm = float(p["LZFPM"])
    lzsk = float(p["LZSK"])
    lzpk = float(p["LZPK"])
    zperc = float(p["ZPERC"])
    rexp = float(p["REXP"])
    weights = _triangle_weights(float(p["UHK"]))
    delay = [0.0] * len(weights)

    uzt = 0.5 * uztwm
    uzf = 0.1 * uzfwm
    lzt = 0.5 * lztwm
    lzfs = 0.2 * lzfsm
    lzfp = 0.4 * lzfpm
    lz_max = lztwm + lzfsm + lzfpm
    discharges: list[float] = []

    for row in inputs:
        precip = float(row[0, 0])
        pet = float(row[0, 1])
        if precip < 0 or pet < 0 or not np.isfinite(precip) or not np.isfinite(pet):
            raise ValueError("invalid SAC-SMA forcing")

        imperv = pctim * precip
        rain = (1.0 - pctim) * precip

        et_uzt = min(uzt, pet * (uzt / uztwm if uztwm > 0 else 0.0))
        uzt = max(0.0, uzt - et_uzt)
        pet_left = max(0.0, pet - et_uzt)
        et_lzt = min(lzt, pet_left * (lzt / lztwm if lztwm > 0 else 0.0))
        lzt = max(0.0, lzt - et_lzt)

        fill_uzt = min(rain, max(0.0, uztwm - uzt))
        uzt += fill_uzt
        rain -= fill_uzt
        fill_uzf = min(rain, max(0.0, uzfwm - uzf))
        uzf += fill_uzf
        surface = max(0.0, rain - fill_uzf)

        deficit = max(0.0, (lztwm - lzt) + (lzfsm - lzfs) + (lzfpm - lzfp))
        ratio = min(1.0, deficit / max(lz_max, 1e-6))
        perc = min(uzf, deficit * (1.0 - math.exp(-zperc * (ratio**rexp))))
        uzf = max(0.0, uzf - perc)

        to_lzt = min(perc, max(0.0, lztwm - lzt))
        lzt += to_lzt
        perc_free = perc - to_lzt
        supp_space = max(0.0, lzfsm - lzfs)
        prim_space = max(0.0, lzfpm - lzfp)
        free_space = supp_space + prim_space
        if perc_free > 0 and free_space > 0:
            to_supp = perc_free * (supp_space / free_space)
            to_prim = perc_free - to_supp
            lzfs = min(lzfsm, lzfs + to_supp)
            lzfp = min(lzfpm, lzfp + to_prim)

        interflow = uzk * uzf
        uzf = max(0.0, uzf - interflow)
        q_supp = lzsk * lzfs
        q_prim = lzpk * lzfp
        lzfs = max(0.0, lzfs - q_supp)
        lzfp = max(0.0, lzfp - q_prim)
        runoff = max(0.0, imperv + surface + interflow + q_supp + q_prim)

        for i in range(len(delay) - 1):
            delay[i] = delay[i + 1] + weights[i] * runoff
        delay[-1] = weights[-1] * runoff
        routed = max(0.0, delay[0])
        discharges.append(runoff_mm_day_to_m3s(float(routed), basin.area_km2))

    values = np.asarray(discharges, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("invalid SAC-SMA numerical result")
    if include_warmup:
        return values
    return values[scheme.warmup_days :]


def load_param_ranges() -> dict[str, tuple[float, float]]:
    return {name: tuple(bounds) for name, bounds in SAC_SMA_PARAMETER_BOUNDS.items()}
