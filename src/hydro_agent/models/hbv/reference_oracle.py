"""Independent hydromad pure-R HBV-light oracle used for parity fixtures.

This module deliberately mirrors ``hydromad`` ``hbv.sim`` / ``hbvrouting.sim``
(Alexander Buzacott port of Seibert & Vis 2012) without importing the product
engine, so residual checks catch accidental equation drift in ``engine.py``.
"""

from __future__ import annotations

import math
from typing import Mapping

import numpy as np


def _integrate_triangle(lo: float, hi: float, maxbas: float) -> float:
    if hi <= lo:
        return 0.0
    mid = maxbas / 2.0
    scale = 4.0 / (maxbas * maxbas)

    def _left(a: float, b: float) -> float:
        return 2.0 * (b * b - a * a) / (maxbas * maxbas)

    def _right(a: float, b: float) -> float:
        return scale * (maxbas * (b - a) - 0.5 * (b * b - a * a))

    if hi <= mid:
        return _left(lo, hi)
    if lo >= mid:
        return _right(lo, hi)
    return _left(lo, mid) + _right(mid, hi)


def maxbas_weights(maxbas: float) -> np.ndarray:
    """Match hydromad: integrate density, then reverse for rollapplyr ordering."""

    maxbas = float(maxbas)
    if maxbas <= 1.0:
        return np.asarray([1.0], dtype=float)
    n = int(math.ceil(maxbas))
    wi = np.asarray(
        [_integrate_triangle(float(i), min(float(i + 1), maxbas), maxbas) for i in range(n)],
        dtype=float,
    )
    return wi[::-1]


def _convolve_maxbas(series: np.ndarray, wi: np.ndarray) -> np.ndarray:
    """Causal rollapplyr(sum(Q * wi)) with left zero padding."""

    n = len(wi)
    padded = np.concatenate([np.zeros(n - 1, dtype=float), np.asarray(series, dtype=float)])
    out = np.empty(len(series), dtype=float)
    for t in range(len(series)):
        window = padded[t : t + n]
        out[t] = float(np.dot(window, wi))
    return out


def simulate_reference(
    precip: np.ndarray,
    temperature: np.ndarray,
    pet: np.ndarray,
    params: Mapping[str, float],
    *,
    initialise_sm: bool = True,
) -> dict[str, np.ndarray]:
    """Return daily mm/day components for the hydromad HBV-light algorithm."""

    p = np.asarray(precip, dtype=float)
    tavg = np.asarray(temperature, dtype=float)
    e = np.asarray(pet, dtype=float)
    n = len(p)
    if not (len(tavg) == n and len(e) == n):
        raise ValueError("forcing length mismatch")

    tt = float(params["TT"])
    cfmax = float(params["CFMAX"])
    sfcf = float(params["SFCF"])
    cfr = float(params["CFR"])
    cwh = float(params["CWH"])
    fc = float(params["FC"])
    lp = float(params["LP"])
    beta = float(params["BETA"])
    perc = float(params["PERC"])
    uzl = float(params["UZL"])
    k0 = float(params["K0"])
    k1 = float(params["K1"])
    k2 = float(params["K2"])
    maxbas = float(params["MAXBAS"])

    snow = np.zeros(n, dtype=float)
    sm = np.zeros(n, dtype=float)
    aet = np.zeros(n, dtype=float)
    recharge = np.zeros(n, dtype=float)
    q0 = np.zeros(n, dtype=float)
    q1 = np.zeros(n, dtype=float)
    q2 = np.zeros(n, dtype=float)
    suz_series = np.zeros(n, dtype=float)
    slz_series = np.zeros(n, dtype=float)

    wc_ = 0.0
    sp_ = 0.0
    sm_ = fc * lp if initialise_sm else 0.0
    suz_ = 0.0
    slz_ = 0.0

    for t in range(n):
        infil_ = 0.0
        sp_tm1 = sp_
        if p[t] > 0.0:
            if tavg[t] > tt:
                wc_ = wc_ + p[t]
            else:
                sp_ = sp_ + p[t] * sfcf
        if tavg[t] > tt:
            melt = cfmax * (tavg[t] - tt)
            if melt > sp_:
                infil_ = sp_ + wc_
                wc_ = 0.0
                sp_ = 0.0
            else:
                sp_ = sp_ - melt
                wc_ = wc_ + melt
                maxwc = sp_ * cwh
                if wc_ > maxwc:
                    infil_ = wc_ - maxwc
                    wc_ = maxwc
        else:
            refr = min(cfr * cfmax * (tt - tavg[t]), wc_)
            sp_ = sp_ + refr
            wc_ = wc_ - refr
        snow[t] = sp_ + wc_

        sm_tm1 = sm_
        if infil_ > 0.0:
            if infil_ < 1.0:
                infil_s = infil_
            else:
                infil_r = int(round(infil_))
                infil_s = infil_ - infil_r
                for _ in range(infil_r):
                    rm = (sm_ / fc) ** beta
                    if rm > 1.0:
                        rm = 1.0
                    sm_ = sm_ + 1.0 - rm
                    recharge[t] = recharge[t] + rm
            rm = (sm_ / fc) ** beta
            if rm > 1.0:
                rm = 1.0
            sm_ = sm_ + (1.0 - rm) * infil_s
            recharge[t] = recharge[t] + rm * infil_s

        if sp_tm1 == 0.0:
            sm_et = (sm_ + sm_tm1) / 2.0
            aet[t] = e[t] * min(sm_et / (fc * lp), 1.0)
            if aet[t] < 0.0:
                aet[t] = 0.0
            if sm_ > aet[t]:
                sm_ = sm_ - aet[t]
            else:
                aet[t] = sm_
                sm_ = 0.0
        sm[t] = sm_

        suz_ = suz_ + recharge[t]
        act_perc = min(suz_, perc)
        suz_ = suz_ - act_perc
        slz_ = slz_ + act_perc
        q0[t] = k0 * max(suz_ - uzl, 0.0)
        q1[t] = k1 * suz_
        suz_ = suz_ - q1[t] - q0[t]
        q2[t] = k2 * slz_
        slz_ = slz_ - q2[t]
        suz_series[t] = suz_
        slz_series[t] = slz_

    wi = maxbas_weights(maxbas)
    q0_r = _convolve_maxbas(q0, wi)
    q1_r = _convolve_maxbas(q1, wi)
    q2_r = _convolve_maxbas(q2, wi)
    qsim = q0_r + q1_r + q2_r

    return {
        "Qsim": qsim,
        "Snow": snow,
        "SM": sm,
        "SUZ": suz_series,
        "SLZ": slz_series,
        "Recharge": recharge,
        "AET": aet,
        "Q0": q0_r,
        "Q1": q1_r,
        "Q2": q2_r,
    }
