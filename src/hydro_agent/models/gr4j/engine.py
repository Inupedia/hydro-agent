"""GR4J daily rainfall-runoff engine (Perrin, Michel & Andréassian, 2003).

Pure NumPy implementation of the published daily GR4J structure:
production store → unit hydrographs UH1/UH2 → groundwater exchange → routing store.
Discharge is returned in m³/s after converting runoff depth with basin area.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .contracts import Gr4jBasin, Gr4jScheme
from .param_groups import GR4J_PARAMETER_BOUNDS

MODEL_VERSION = "gr4j-v1-20260316"
MODEL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _ss1(t: float, x4: float) -> float:
    if t <= 0:
        return 0.0
    if t < x4:
        return (t / x4) ** 2.5
    return 1.0


def _ss2(t: float, x4: float) -> float:
    if t <= 0:
        return 0.0
    if t <= x4:
        return 0.5 * (t / x4) ** 2.5
    if t < 2.0 * x4:
        return 1.0 - 0.5 * (2.0 - t / x4) ** 2.5
    return 1.0


def _unit_hydrograph(ordinates: int, x4: float, kind: str) -> list[float]:
    weights: list[float] = []
    for i in range(1, ordinates + 1):
        if kind == "uh1":
            weights.append(_ss1(float(i), x4) - _ss1(float(i - 1), x4))
        else:
            weights.append(_ss2(float(i), x4) - _ss2(float(i - 1), x4))
    total = sum(weights)
    if total <= 0:
        raise ValueError("invalid GR4J unit hydrograph")
    return [w / total for w in weights]


def runoff_mm_day_to_m3s(runoff_mm_day: float, area_km2: float) -> float:
    return runoff_mm_day * area_km2 * 1000.0 / 86400.0


def simulate(scheme: Gr4jScheme, basin: Gr4jBasin, inputs, *, include_warmup: bool = False):
    """Return discharge in m³/s; by default drop the warm-up prefix.

    ``inputs`` is shaped ``(n_days, 1, 2)`` with columns precipitation and PET
    in mm/day — the same forcing layout used by the XAJ sandbox contract.
    """

    import numpy as np

    p = scheme.parameters
    x1 = float(p["X1"])
    x2 = float(p["X2"])
    x3 = float(p["X3"])
    x4 = float(p["X4"])

    n_uh1 = int(max(1, np.ceil(x4)))
    n_uh2 = int(max(1, np.ceil(2.0 * x4)))
    uh1 = _unit_hydrograph(n_uh1, x4, "uh1")
    uh2 = _unit_hydrograph(n_uh2, x4, "uh2")
    q_uh1 = [0.0] * n_uh1
    q_uh2 = [0.0] * n_uh2

    production = 0.0
    routing = 0.0
    discharges: list[float] = []

    for row in inputs:
        precip = float(row[0, 0])
        pet = float(row[0, 1])
        if precip < 0 or pet < 0 or not np.isfinite(precip) or not np.isfinite(pet):
            raise ValueError("invalid GR4J forcing")

        if precip >= pet:
            pn = precip - pet
            en = 0.0
            mapped = (
                x1 * (1.0 - (production / x1) ** 2) * np.tanh(pn / x1)
                / (1.0 + (production / x1) * np.tanh(pn / x1))
            )
            production = production + mapped
            ps = pn - mapped
        else:
            ps = 0.0
            en = pet - precip
            production = production * (
                1.0
                - np.tanh(en / x1)
                / (1.0 + (1.0 - (production / x1) / 2.0) * np.tanh(en / x1))
            )

        perc = production * (1.0 - (1.0 + (production / (9.0 / 4.0 * x1)) ** 4) ** -0.25)
        production = production - perc
        pr = perc + ps

        for i in range(n_uh1 - 1):
            q_uh1[i] = q_uh1[i + 1] + uh1[i] * pr
        q_uh1[-1] = uh1[-1] * pr
        for i in range(n_uh2 - 1):
            q_uh2[i] = q_uh2[i + 1] + uh2[i] * pr
        q_uh2[-1] = uh2[-1] * pr

        q9 = q_uh1[0]
        q1 = q_uh2[0]
        f = x2 * ((routing / x3) ** 3.5)
        routing = max(0.0, routing + q9 + f)
        qr = routing * (1.0 - (1.0 + (routing / x3) ** 4) ** -0.25)
        routing = max(0.0, routing - qr)
        qd = max(0.0, q1 + f)
        runoff_mm = qr + qd
        discharges.append(runoff_mm_day_to_m3s(float(runoff_mm), basin.area_km2))

    values = np.asarray(discharges, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("invalid GR4J numerical result")
    if include_warmup:
        return values
    return values[scheme.warmup_days :]


def load_param_ranges() -> dict[str, tuple[float, float]]:
    return {name: tuple(bounds) for name, bounds in GR4J_PARAMETER_BOUNDS.items()}
