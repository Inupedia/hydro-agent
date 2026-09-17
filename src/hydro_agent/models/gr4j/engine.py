"""GR4J daily rainfall-runoff engine (Perrin, Michel & Andréassian, 2003).

Pure NumPy implementation of the published daily GR4J structure:
production store → unit hydrographs UH1/UH2 → groundwater exchange → routing store.
Discharge is returned in m³/s after converting runoff depth with basin area.

The 90%/10% UH split uses ``float32(0.9)`` then promotes to float64 — the same
single-precision literal airGR's Fortran evaluates — so daily states and Qsim
match the airGR-aligned GRsuite oracle to ~1e-14 mm/d.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .contracts import Gr4jBasin, Gr4jScheme
from .param_groups import GR4J_PARAMETER_BOUNDS

MODEL_VERSION = "gr4j-v1-20260917"
MODEL_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _uh_split_coefficients() -> tuple[float, float]:
    """airGR Fortran evaluates the UH split coefficient in single precision."""

    import numpy as np

    to_routing = float(np.float32(0.9))
    return to_routing, 1.0 - to_routing


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


def _run(
    scheme: Gr4jScheme,
    basin: Gr4jBasin,
    inputs,
    *,
    include_warmup: bool,
    collect_diagnostics: bool,
    init_production: float | None = None,
    init_routing: float | None = None,
    init_uh1: list[float] | None = None,
    init_uh2: list[float] | None = None,
) -> Any:
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
    q_uh1 = list(init_uh1) if init_uh1 is not None else [0.0] * n_uh1
    q_uh2 = list(init_uh2) if init_uh2 is not None else [0.0] * n_uh2
    if len(q_uh1) != n_uh1 or len(q_uh2) != n_uh2:
        raise ValueError("GR4J UH initial state length mismatch")

    # Standard GR4J / airGR initialization (IniResLevels 0.3 / 0.5).
    production = 0.3 * x1 if init_production is None else float(init_production)
    routing = 0.5 * x3 if init_routing is None else float(init_routing)
    split_routing, split_direct = _uh_split_coefficients()
    discharges: list[float] = []
    diagnostics: dict[str, list[float]] | None = (
        {
            "Prod": [],
            "Pn": [],
            "Ps": [],
            "Perc": [],
            "PR": [],
            "Q9": [],
            "Q1": [],
            "Rout": [],
            "Exch": [],
            "QR": [],
            "QD": [],
            "Qsim": [],
        }
        if collect_diagnostics
        else None
    )

    for row in inputs:
        precip = float(row[0, 0])
        pet = float(row[0, 1])
        if precip < 0 or pet < 0 or not np.isfinite(precip) or not np.isfinite(pet):
            raise ValueError("invalid GR4J forcing")

        if precip >= pet:
            pn = precip - pet
            mapped = (
                x1
                * (1.0 - (production / x1) ** 2)
                * np.tanh(pn / x1)
                / (1.0 + (production / x1) * np.tanh(pn / x1))
            )
            production = production + mapped
            ps = mapped
            excess = pn - mapped
        else:
            pn = 0.0
            ps = 0.0
            excess = 0.0
            en = pet - precip
            tanh_en = np.tanh(en / x1)
            evap_from_store = (
                production
                * (2.0 - production / x1)
                * tanh_en
                / (1.0 + (1.0 - production / x1) * tanh_en)
            )
            production = max(0.0, production - evap_from_store)

        perc = production * (1.0 - (1.0 + (production / (9.0 / 4.0 * x1)) ** 4) ** -0.25)
        production = production - perc
        pr = perc + excess

        # Perrin et al. (2003): 90% through UH1 → routing store, 10% through UH2.
        routed_uh1 = split_routing * pr
        routed_uh2 = split_direct * pr
        for i in range(n_uh1 - 1):
            q_uh1[i] = q_uh1[i + 1] + uh1[i] * routed_uh1
        q_uh1[-1] = uh1[-1] * routed_uh1
        for i in range(n_uh2 - 1):
            q_uh2[i] = q_uh2[i + 1] + uh2[i] * routed_uh2
        q_uh2[-1] = uh2[-1] * routed_uh2

        q9 = q_uh1[0]
        q1 = q_uh2[0]
        f = x2 * ((routing / x3) ** 3.5)
        routing = max(0.0, routing + q9 + f)
        qr = routing * (1.0 - (1.0 + (routing / x3) ** 4) ** -0.25)
        routing = max(0.0, routing - qr)
        qd = max(0.0, q1 + f)
        runoff_mm = qr + qd
        discharges.append(runoff_mm_day_to_m3s(float(runoff_mm), basin.area_km2))

        if diagnostics is not None:
            diagnostics["Prod"].append(float(production))
            diagnostics["Pn"].append(float(pn))
            diagnostics["Ps"].append(float(ps))
            diagnostics["Perc"].append(float(perc))
            diagnostics["PR"].append(float(pr))
            diagnostics["Q9"].append(float(q9))
            diagnostics["Q1"].append(float(q1))
            diagnostics["Rout"].append(float(routing))
            diagnostics["Exch"].append(float(f))
            diagnostics["QR"].append(float(qr))
            diagnostics["QD"].append(float(qd))
            diagnostics["Qsim"].append(float(runoff_mm))

    values = np.asarray(discharges, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("invalid GR4J numerical result")
    state_end = {
        "production": float(production),
        "routing": float(routing),
        "uh1": list(q_uh1),
        "uh2": list(q_uh2),
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


def simulate(scheme: Gr4jScheme, basin: Gr4jBasin, inputs, *, include_warmup: bool = False):
    """Return discharge in m³/s; by default drop the warm-up prefix.

    ``inputs`` is shaped ``(n_days, 1, 2)`` with columns precipitation and PET
    in mm/day — the same forcing layout used by the XAJ sandbox contract.
    """

    return _run(
        scheme, basin, inputs, include_warmup=include_warmup, collect_diagnostics=False
    )


def simulate_diagnostics(
    scheme: Gr4jScheme,
    basin: Gr4jBasin,
    inputs,
    *,
    include_warmup: bool = True,
    init_production: float | None = None,
    init_routing: float | None = None,
    init_uh1: list[float] | None = None,
    init_uh2: list[float] | None = None,
) -> dict[str, Any]:
    """Return airGR-named daily series (mm/d or mm) plus discharge (m³/s).

    Keys match airGR ``OutputsModel`` names used by the registered parity oracle:
    ``Prod``, ``Pn``, ``Ps``, ``Perc``, ``PR``, ``Q9``, ``Q1``, ``Rout``,
    ``Exch``, ``QR``, ``QD``, ``Qsim`` (mm/d), ``discharge_m3s``, and ``StateEnd``.
    """

    discharge, diagnostics, state_end = _run(
        scheme,
        basin,
        inputs,
        include_warmup=include_warmup,
        collect_diagnostics=True,
        init_production=init_production,
        init_routing=init_routing,
        init_uh1=init_uh1,
        init_uh2=init_uh2,
    )
    diagnostics["discharge_m3s"] = discharge
    diagnostics["StateEnd"] = state_end
    return diagnostics


def load_param_ranges() -> dict[str, tuple[float, float]]:
    return {name: tuple(bounds) for name, bounds in GR4J_PARAMETER_BOUNDS.items()}
