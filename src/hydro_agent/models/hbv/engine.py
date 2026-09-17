"""HBV-light daily engine (Seibert & Vis 2012 / hydromad-aligned).

Lumped snow + soil + groundwater with continuous MAXBAS triangular routing.
Discharge is returned in m³/s after converting runoff depth with basin area.
Forcing columns follow ``required_forcings``: precipitation, temperature, PET.

CET / mean-PET reconstruction is out of scope: daily PET is required as forcing.
Elevation/vegetation zones are out of lumped product scope.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from .contracts import HbvBasin, HbvScheme
from .param_groups import HBV_PARAMETER_BOUNDS

MODEL_VERSION = "hbv-light-v2-20260917"
MODEL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def runoff_mm_day_to_m3s(runoff_mm_day: float, area_km2: float) -> float:
    return runoff_mm_day * area_km2 * 1000.0 / 86400.0


def m3s_to_runoff_mm_day(discharge_m3s: float, area_km2: float) -> float:
    return discharge_m3s * 86400.0 / (area_km2 * 1000.0)


def maxbas_triangle_weights(maxbas: float) -> list[float]:
    """Continuous triangular MAXBAS weights (Seibert & Vis 2012 eq. 6).

    Integrates the piecewise-linear density on each day interval ``[i, i+1)``
    clipped to ``[0, MAXBAS]``. Weights are ordered so index 0 is the
    same-day contribution (hydromad reverses before ``rollapplyr``).
    """

    maxbas = float(maxbas)
    if maxbas <= 1.0:
        return [1.0]
    n = int(math.ceil(maxbas))
    weights = [_integrate_triangle(float(i), min(float(i + 1), maxbas), maxbas) for i in range(n)]
    total = sum(weights)
    if total <= 0.0:
        return [1.0]
    # Numerical guard; analytic integral already sums to 1 within float error.
    return [w / total for w in weights]


def _integrate_triangle(lo: float, hi: float, maxbas: float) -> float:
    if hi <= lo:
        return 0.0
    mid = maxbas / 2.0
    scale = 4.0 / (maxbas * maxbas)

    def _left(a: float, b: float) -> float:
        # ∫ 4u/M² du = 2(b² − a²)/M²
        return 2.0 * (b * b - a * a) / (maxbas * maxbas)

    def _right(a: float, b: float) -> float:
        # ∫ 4(M − u)/M² du
        return scale * (maxbas * (b - a) - 0.5 * (b * b - a * a))

    if hi <= mid:
        return _left(lo, hi)
    if lo >= mid:
        return _right(lo, hi)
    return _left(lo, mid) + _right(mid, hi)


def simulate(scheme: HbvScheme, basin: HbvBasin, inputs, *, include_warmup: bool = False):
    """Return discharge in m³/s; by default drop the warm-up prefix."""

    return _run(
        scheme,
        basin,
        inputs,
        include_warmup=include_warmup,
        collect_diagnostics=False,
    )


def simulate_diagnostics(
    scheme: HbvScheme,
    basin: HbvBasin,
    inputs,
    *,
    include_warmup: bool = False,
    init_snow: float | None = None,
    init_liquid: float | None = None,
    init_soil: float | None = None,
    init_suz: float | None = None,
    init_slz: float | None = None,
    init_delay: list[float] | None = None,
) -> dict[str, Any]:
    """Return daily diagnostic series in mm/day plus ending state."""

    values, diagnostics, state_end = _run(
        scheme,
        basin,
        inputs,
        include_warmup=include_warmup,
        collect_diagnostics=True,
        init_snow=init_snow,
        init_liquid=init_liquid,
        init_soil=init_soil,
        init_suz=init_suz,
        init_slz=init_slz,
        init_delay=init_delay,
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
    scheme: HbvScheme,
    basin: HbvBasin,
    inputs,
    *,
    include_warmup: bool,
    collect_diagnostics: bool,
    init_snow: float | None = None,
    init_liquid: float | None = None,
    init_soil: float | None = None,
    init_suz: float | None = None,
    init_slz: float | None = None,
    init_delay: list[float] | None = None,
) -> Any:
    import numpy as np

    p = scheme.parameters
    tt = float(p["TT"])
    cfmax = float(p["CFMAX"])
    sfcf = float(p["SFCF"])
    cfr = float(p["CFR"])
    cwh = float(p["CWH"])
    fc = float(p["FC"])
    beta = float(p["BETA"])
    lp = float(p["LP"])
    k0 = float(p["K0"])
    k1 = float(p["K1"])
    k2 = float(p["K2"])
    perc = float(p["PERC"])
    uzl = float(p["UZL"])
    weights = maxbas_triangle_weights(float(p["MAXBAS"]))
    n_w = len(weights)

    def _new_delay() -> list[float]:
        return [0.0] * n_w

    if init_delay is None:
        delay0, delay1, delay2 = _new_delay(), _new_delay(), _new_delay()
    else:
        # Resume expects concatenated [d0|d1|d2] of length 3 * n_w.
        flat = [float(v) for v in init_delay]
        if len(flat) != 3 * n_w:
            raise ValueError("HBV MAXBAS delay initial state length mismatch")
        delay0 = flat[0:n_w]
        delay1 = flat[n_w : 2 * n_w]
        delay2 = flat[2 * n_w :]

    # HBV-light default soil moisture = FC * LP (hydromad initialise_sm=True).
    sp = 0.0 if init_snow is None else float(init_snow)
    wc = 0.0 if init_liquid is None else float(init_liquid)
    sm = (fc * lp) if init_soil is None else float(init_soil)
    suz = 0.0 if init_suz is None else float(init_suz)
    slz = 0.0 if init_slz is None else float(init_slz)

    discharges: list[float] = []
    diagnostics: dict[str, list[float]] | None = (
        {
            "Snow": [],
            "SM": [],
            "SUZ": [],
            "SLZ": [],
            "Recharge": [],
            "AET": [],
            "Q0": [],
            "Q1": [],
            "Q2": [],
        }
        if collect_diagnostics
        else None
    )

    def _push(delay: list[float], amount: float) -> float:
        for i in range(n_w - 1):
            delay[i] = delay[i + 1] + weights[i] * amount
        delay[-1] = weights[-1] * amount
        return max(0.0, delay[0])

    for row in inputs:
        precip = float(row[0, 0])
        temp = float(row[0, 1])
        pet = float(row[0, 2])
        if precip < 0 or pet < 0 or not np.isfinite([precip, pet, temp]).all():
            raise ValueError("invalid HBV forcing")

        sp_tm1 = sp
        infil = 0.0

        # --- Snow routine (hydromad hbv.sim pure-R) ---
        if precip > 0.0:
            if temp > tt:
                wc += precip
            else:
                sp += precip * sfcf

        if temp > tt:
            melt = cfmax * (temp - tt)
            if melt > sp:
                infil = sp + wc
                wc = 0.0
                sp = 0.0
            else:
                sp -= melt
                wc += melt
                max_wc = sp * cwh
                if wc > max_wc:
                    infil = wc - max_wc
                    wc = max_wc
        else:
            refr = min(cfr * cfmax * (tt - temp), wc)
            sp += refr
            wc -= refr

        # --- Soil routine ---
        recharge = 0.0
        sm_tm1 = sm
        if infil > 0.0:
            if infil < 1.0:
                frac = infil
                rm = min(1.0, (sm / fc) ** beta) if fc > 0 else 1.0
                sm = sm + (1.0 - rm) * frac
                recharge += rm * frac
            else:
                whole = int(round(infil))
                frac = infil - whole
                for _ in range(whole):
                    rm = min(1.0, (sm / fc) ** beta) if fc > 0 else 1.0
                    sm = sm + 1.0 - rm
                    recharge += rm
                rm = min(1.0, (sm / fc) ** beta) if fc > 0 else 1.0
                sm = sm + (1.0 - rm) * frac
                recharge += rm * frac

        aet = 0.0
        # AET only when previous day had no snow pack water (solid store only).
        if sp_tm1 == 0.0:
            sm_et = (sm + sm_tm1) / 2.0
            aet = pet * min(sm_et / max(fc * lp, 1e-12), 1.0)
            aet = max(0.0, aet)
            if sm > aet:
                sm -= aet
            else:
                aet = sm
                sm = 0.0

        # --- Groundwater ---
        suz += recharge
        act_perc = min(suz, perc)
        suz -= act_perc
        slz += act_perc
        q0 = k0 * max(suz - uzl, 0.0)
        q1 = k1 * suz
        suz = suz - q0 - q1
        q2 = k2 * slz
        slz = slz - q2

        # Route Q0/Q1/Q2 separately (hydromad hbvrouting.sim).
        rq0 = _push(delay0, q0)
        rq1 = _push(delay1, q1)
        rq2 = _push(delay2, q2)
        routed = max(0.0, rq0 + rq1 + rq2)
        discharges.append(runoff_mm_day_to_m3s(float(routed), basin.area_km2))

        if diagnostics is not None:
            diagnostics["Snow"].append(sp + wc)
            diagnostics["SM"].append(sm)
            diagnostics["SUZ"].append(suz)
            diagnostics["SLZ"].append(slz)
            diagnostics["Recharge"].append(recharge)
            diagnostics["AET"].append(aet)
            diagnostics["Q0"].append(rq0)
            diagnostics["Q1"].append(rq1)
            diagnostics["Q2"].append(rq2)

    values = np.asarray(discharges, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("invalid HBV numerical result")
    state_end = {
        "snow": float(sp),
        "liquid": float(wc),
        "soil": float(sm),
        "suz": float(suz),
        "slz": float(slz),
        "delay": list(delay0) + list(delay1) + list(delay2),
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
    return {name: tuple(bounds) for name, bounds in HBV_PARAMETER_BOUNDS.items()}
