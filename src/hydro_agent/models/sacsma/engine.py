"""NOAA-OWP SAC-SMA daily engine (full 16-parameter soil-moisture accounting).

Faithful Python port of the NOAA-OWP ``sac-sma`` core (``SAC1``/``EXSAC``):
incremental sub-time steps, ADIMP saturation-excess direct runoff, PFREE
percolation split, RIVA riparian evapotranspiration, SIDE baseflow bypass,
and RSERV-protected lower-zone tension-water recharge.  ``HOURS`` drives an
optional daily triangular unit-hydrograph routing layer and is **not** part
of the official SAC-SMA parameter set.

Discharge is returned in m³/s after converting runoff depth with basin area.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from .contracts import (
    SacSmaBasin,
    SacSmaScheme,
    initial_state_from_parameters,
)
from .param_groups import SAC_SMA_PARAMETER_BOUNDS

MODEL_VERSION = "sac-sma-v2-20260917"
MODEL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def runoff_mm_day_to_m3s(runoff_mm_day: float, area_km2: float) -> float:
    return runoff_mm_day * area_km2 * 1000.0 / 86400.0


def _triangle_weights_hourly(base_hours: float) -> list[float]:
    """Triangular unit-hydrograph ordinates (hourly increments, unit integral)."""
    n = max(1, int(math.ceil(float(base_hours))))
    mid = (n + 1) / 2.0
    weights = [max(0.0, 1.0 - abs((i + 1) - mid) / mid) for i in range(n)]
    total = sum(weights)
    return [w / total for w in weights]


def _daily_routing_weights(base_hours: float) -> list[float]:
    """Collapse the hourly triangular UH onto a daily lag line."""
    if base_hours <= 0.0:
        return [1.0]
    hourly = _triangle_weights_hourly(base_hours)
    n_days = int(math.ceil(len(hourly) / 24))
    daily = [0.0] * max(1, n_days)
    for k, w in enumerate(hourly):
        daily[k // 24] += w
    return daily


def _run_sma_day(
    *,
    precip: float,
    pet: float,
    p: dict[str, float],
    state: dict[str, float],
    dt: float,
) -> dict[str, float]:
    """Execute one NOAA-OWP SAC-SMA soil-moisture accounting day.

    Returns updated states plus aggregated runoff components (mm/day):
    ROIMP, SDRO, SSUR, SIF, BFS, BFP, BFNCC, ETA.
    """

    uztwm = float(p["UZTWM"])
    uzfwm = float(p["UZFWM"])
    uzk = float(p["UZK"])
    pctim = float(p["PCTIM"])
    adimp = float(p["ADIMP"])
    riva = float(p["RIVA"])
    zperc = float(p["ZPERC"])
    rexp = float(p["REXP"])
    lztwm = float(p["LZTWM"])
    lzfsm = float(p["LZFSM"])
    lzfpm = float(p["LZFPM"])
    lzsk = float(p["LZSK"])
    lzpk = float(p["LZPK"])
    pfree = float(p["PFREE"])
    side = float(p["SIDE"])
    rserv = float(p["RSERV"])

    uztwc = float(state["UZTWC"])
    uzfwc = float(state["UZFWC"])
    lztwc = float(state["LZTWC"])
    lzfsc = float(state["LZFSC"])
    lzfpc = float(state["LZFPC"])
    adimc = float(state["ADIMC"])

    # ---------- ET from upper zone (E1/E2) ----------
    edmnd = pet
    e1 = edmnd * (uztwc / uztwm)
    red = edmnd - e1
    uztwc = uztwc - e1
    e2 = 0.0
    bypass_ratio_check = False
    if uztwc < 0.0:
        e1 = e1 + uztwc
        uztwc = 0.0
        red = edmnd - e1
        if uzfwc >= red:
            e2 = red
            uzfwc = uzfwc - e2
            red = 0.0
        else:
            e2 = uzfwc
            uzfwc = 0.0
            red = red - e2
            bypass_ratio_check = True

    # Upper-zone free/tension redistribution.
    if not bypass_ratio_check:
        if (uztwc / uztwm) < (uzfwc / uzfwm):
            uzrat = (uztwc + uzfwc) / (uztwm + uzfwm)
            uztwc = uztwm * uzrat
            uzfwc = uzfwm * uzrat

    # ---------- ET from lower zone tension water (E3) ----------
    e3 = red * (lztwc / (uztwm + lztwm))
    lztwc = lztwc - e3
    if lztwc < 0.0:
        e3 = e3 + lztwc
        lztwc = 0.0

    # ---------- RSERV-protected tension-water recharge (DEL) ----------
    ratlzt = lztwc / lztwm
    saved = rserv * (lzfpm + lzfsm)
    ratlz = (lztwc + lzfpc + lzfsc - saved) / (lztwm + lzfpm + lzfsm - saved)
    if ratlzt < ratlz:
        del_water = (ratlz - ratlzt) * lztwm
        lztwc = lztwc + del_water
        lzfsc = lzfsc - del_water
        if lzfsc < 0.0:
            lzfpc = lzfpc + lzfsc
            lzfsc = 0.0

    # ---------- ET from ADIMP area (E5) ----------
    e5 = e1 + (red + e2) * ((adimc - e1 - uztwc) / (uztwm + lztwm))
    adimc = adimc - e5
    if adimc < 0.0:
        e5 = e5 + adimc
        adimc = 0.0
    e5 = e5 * adimp

    # ---------- Pervious-area moisture accounting ----------
    twx = precip + uztwc - uztwm
    if twx < 0.0:
        uztwc = uztwc + precip
        twx = 0.0
    else:
        uztwc = uztwm
    adimc = adimc + precip - twx

    # Impervious runoff.
    roimp = precip * pctim

    # ---------- Incremental loop (sub-time increments) ----------
    ninc = max(1, int(1.0 + 0.2 * (uzfwc + twx)))
    dinc = dt / float(ninc)
    pinc = twx / float(ninc)
    duz = 1.0 - ((1.0 - uzk) ** dinc)
    dlzp = 1.0 - ((1.0 - lzpk) ** dinc)
    dlzs = 1.0 - ((1.0 - lzsk) ** dinc)
    parea = 1.0 - adimp - pctim

    sbf = 0.0
    ssur = 0.0
    sif = 0.0
    sdro = 0.0
    sperc = 0.0
    spbf = 0.0

    for _ in range(ninc):
        adsur = 0.0
        ratio = (adimc - uztwc) / lztwm
        if ratio < 0.0:
            ratio = 0.0
        addro = pinc * (ratio**2)

        # Primary baseflow.
        bf = lzfpc * dlzp
        lzfpc = lzfpc - bf
        if lzfpc <= 0.0001:
            bf = bf + lzfpc
            lzfpc = 0.0
        sbf += bf
        spbf += bf

        # Secondary baseflow.
        bf = lzfsc * dlzs
        lzfsc = lzfsc - bf
        if lzfsc <= 0.0001:
            bf = bf + lzfsc
            lzfsc = 0.0
        sbf += bf

        # Percolation: skip when no available water.
        if (pinc + uzfwc) <= 0.01:
            uzfwc = uzfwc + pinc
            adimc = adimc + pinc - addro - adsur
            if adimc > (uztwm + lztwm):
                addro = addro + adimc - (uztwm + lztwm)
                adimc = uztwm + lztwm
            sdro = sdro + addro * adimp
            continue

        percm = lzfpm * dlzp + lzfsm * dlzs
        perc = percm * (uzfwc / uzfwm)
        defr = 1.0 - ((lztwc + lzfpc + lzfsc) / (lztwm + lzfpm + lzfsm))
        perc = perc * (1.0 + zperc * (defr**rexp))
        if perc >= uzfwc:
            perc = uzfwc
        uzfwc = uzfwc - perc

        # Percolation must not exceed lower-zone deficiency.
        check_val = lztwc + lzfpc + lzfsc + perc - lztwm - lzfpm - lzfsm
        if check_val > 0.0:
            perc = perc - check_val
            uzfwc = uzfwc + check_val
        sperc = sperc + perc

        # Interflow.
        del_water = uzfwc * duz
        sif = sif + del_water
        uzfwc = uzfwc - del_water

        # Distribute percolation to lower zone (tension first, PFREE split).
        perct = perc * (1.0 - pfree)
        if (perct + lztwc) <= lztwm:
            lztwc = lztwc + perct
            percf = 0.0
        else:
            percf = perct + lztwc - lztwm
            lztwc = lztwm
        percf = percf + perc * pfree

        if percf != 0.0:
            hpl = lzfpm / (lzfpm + lzfsm)
            ratlp = lzfpc / lzfpm
            ratls = lzfsc / lzfsm
            fracp = (hpl * 2.0 * (1.0 - ratlp)) / ((1.0 - ratlp) + (1.0 - ratls))
            if fracp > 1.0:
                fracp = 1.0
            perc_p = percf * fracp
            perc_s = percf - perc_p
            lzfsc = lzfsc + perc_s
            if lzfsc > lzfsm:
                perc_s = perc_s - lzfsc + lzfsm
                lzfsc = lzfsm
            lzfpc = lzfpc + (percf - perc_s)
            if lzfpc > lzfpm:
                excess = lzfpc - lzfpm
                lztwc = lztwc + excess
                lzfpc = lzfpm

        # Surface runoff from upper-zone free water after rain addition.
        if pinc != 0.0:
            if (pinc + uzfwc) > uzfwm:
                sur = pinc + uzfwc - uzfwm
                uzfwc = uzfwm
                ssur = ssur + sur * parea
                adsur = sur * (1.0 - addro / pinc)
                ssur = ssur + adsur * adimp
            else:
                uzfwc = uzfwc + pinc

        # ADIMP-area water balance.
        adimc = adimc + pinc - addro - adsur
        if adimc > (uztwm + lztwm):
            addro = addro + adimc - (uztwm + lztwm)
            adimc = uztwm + lztwm
        sdro = sdro + addro * adimp

    # ---------- Post-loop aggregation and RIVA/SIDE ----------
    eused = e1 + e2 + e3
    sif = sif * parea
    tbf = sbf * parea
    bfcc = tbf * (1.0 / (1.0 + side))
    bfp = spbf * parea / (1.0 + side)
    bfs = bfcc - bfp
    if bfs < 0.0:
        bfs = 0.0
    bfncc = tbf - bfcc
    tci = roimp + sdro + ssur + sif + bfcc

    # Riparian evapotranspiration (RIVA).
    e4 = (edmnd - eused) * riva
    tci = tci - e4
    if tci < 0.0:
        e4 = e4 + tci
        tci = 0.0

    eused = eused * parea
    eta = eused + e5 + e4
    if adimc < uztwc:
        adimc = uztwc

    return {
        "UZTWC": uztwc,
        "UZFWC": uzfwc,
        "LZTWC": lztwc,
        "LZFSC": lzfsc,
        "LZFPC": lzfpc,
        "ADIMC": adimc,
        "ROIMP": roimp,
        "SDRO": sdro,
        "SSUR": ssur,
        "SIF": sif,
        "BFS": bfs,
        "BFP": bfp,
        "BFNCC": bfncc,
        "ETA": eta,
        "TCI": tci,
    }


def simulate(scheme: SacSmaScheme, basin: SacSmaBasin, inputs, *, include_warmup: bool = False):
    """Return discharge in m³/s; by default drop the warm-up prefix.

    ``inputs`` is shaped ``(n_days, 1, 2)`` with precipitation and PET in mm/day.
    """

    import numpy as np

    p = scheme.parameters
    state = initial_state_from_parameters(p)
    routing_weights = _daily_routing_weights(float(scheme.routing["HOURS"]))
    delay = [0.0] * len(routing_weights)
    discharges: list[float] = []

    for row in inputs:
        precip = float(row[0, 0])
        pet = float(row[0, 1])
        if precip < 0 or pet < 0 or not np.isfinite(precip) or not np.isfinite(pet):
            raise ValueError("invalid SAC-SMA forcing")

        out = _run_sma_day(
            precip=precip,
            pet=pet,
            p=p,
            state=state,
            dt=1.0,
        )
        state = {k: out[k] for k in ("UZTWC", "UZFWC", "LZTWC", "LZFSC", "LZFPC", "ADIMC")}
        basin_q = out["TCI"]

        for i in range(len(delay) - 1):
            delay[i] = delay[i + 1] + routing_weights[i] * basin_q
        delay[-1] = routing_weights[-1] * basin_q
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
