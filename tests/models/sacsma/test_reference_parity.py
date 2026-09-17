"""SAC-SMA reference parity and numerical stress gates for source_verified unlock."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from hydro_agent.models.registry import default_model_registry
from hydro_agent.models.sacsma.contracts import (
    SacSmaBasin,
    SacSmaScheme,
    initial_state_from_parameters,
)
from hydro_agent.models.sacsma.engine import _run_sma_day, simulate
from hydro_agent.models.sacsma.parity import (
    PARITY_ABS_MM_DAY,
    REFERENCE_ORACLE,
    REFERENCE_PARAMS,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "sacsma"


def _scheme(params: dict[str, float] | None = None, *, warmup_days: int = 1) -> SacSmaScheme:
    return SacSmaScheme(
        model_id="sac-sma",
        warmup_days=warmup_days,
        routing={"HOURS": 4.0},
        parameters=dict(params or REFERENCE_PARAMS),
    )


def _basin(area_km2: float = 1.0) -> SacSmaBasin:
    return SacSmaBasin(basin_id="sac-sma-parity", area_km2=area_km2)


def _forcing(precip, pet) -> np.ndarray:
    precip = np.asarray(precip, dtype=float)
    pet = np.asarray(pet, dtype=float)
    return np.stack([precip, pet], axis=-1)[:, None, :]


def test_sacsma_plugin_is_source_verified_for_product_calibration():
    descriptor = default_model_registry().get("sac-sma").descriptor
    assert descriptor.validation_status == "source_verified"
    assert descriptor.supports_calibration is True
    assert REFERENCE_ORACLE in (descriptor.technical_reference or "")


def _components(engine_fn, precip, pet, params):
    keys = (
        "UZTWC",
        "UZFWC",
        "LZTWC",
        "LZFSC",
        "LZFPC",
        "ADIMC",
        "ROIMP",
        "SDRO",
        "SSUR",
        "SIF",
        "BFS",
        "BFP",
        "BFNCC",
        "ETA",
        "TCI",
    )
    n = len(precip)
    out = {key: np.zeros(n, dtype=float) for key in keys}
    state = initial_state_from_parameters(params)
    for t in range(n):
        day = engine_fn(precip=float(precip[t]), pet=float(pet[t]), p=params, state=state, dt=1.0)
        for key in keys:
            out[key][t] = day[key]
        state = {k: day[k] for k in ("UZTWC", "UZFWC", "LZTWC", "LZFSC", "LZFPC", "ADIMC")}
    return out


def test_daily_components_match_pinned_noaa_fortran_output():
    """Compare against upstream executable output, not a second Python port."""
    with (FIXTURES / "noaa_owp_synthetic_400d.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    precip = np.asarray([float(row["precipitation_mm"]) for row in rows])
    pet = np.asarray([float(row["pet_mm"]) for row in rows])
    ours = _components(_run_sma_day, precip, pet, dict(REFERENCE_PARAMS))
    for key, values in ours.items():
        expected = np.asarray([float(row[key]) for row in rows])
        tolerance = PARITY_ABS_MM_DAY.get(key, 1e-9)
        assert float(np.max(np.abs(values - expected))) <= tolerance, key


def test_random_forcing_closes_daily_water_balance():
    params = dict(REFERENCE_PARAMS)
    state = initial_state_from_parameters(params)
    pervious_area = 1.0 - params["PCTIM"] - params["ADIMP"]
    rng = np.random.default_rng(20260917)
    for _ in range(1_000):
        precip = float(rng.gamma(1.2, 8.0) if rng.random() < 0.35 else 0.0)
        pet = float(rng.uniform(0.0, 8.0))
        previous = dict(state)
        out = _run_sma_day(precip=precip, pet=pet, p=params, state=state, dt=1.0)
        state = {key: out[key] for key in previous}
        storage_delta = pervious_area * sum(
            state[key] - previous[key] for key in ("UZTWC", "UZFWC", "LZTWC", "LZFSC", "LZFPC")
        ) + params["ADIMP"] * (state["ADIMC"] - previous["ADIMC"])
        residual = precip - (out["ETA"] + out["TCI"] + out["BFNCC"] + storage_delta)
        assert abs(residual) <= 1e-10


def test_zero_precipitation_and_constant_event_stress():
    for days, pet in ((120, 2.5), (200, 1.0), (200, 5.0)):
        precip = np.zeros(days)
        q = simulate(_scheme(), _basin(), _forcing(precip, np.full(days, pet)), include_warmup=True)
        assert np.isfinite(q).all() and (q >= 0).all()
    precip = np.full(200, 5.0)
    q = simulate(_scheme(), _basin(), _forcing(precip, np.full(200, 1.0)), include_warmup=True)
    assert np.isfinite(q).all() and (q >= 0).all()
    assert float(q.sum()) > 0.0


def test_extreme_parameters_remain_finite_and_nonnegative():
    days = 90
    precip = np.linspace(0.0, 80.0, days)
    pet = np.full(days, 3.0)
    extremes = (
        {
            "UZTWM": 1.0,
            "UZFWM": 1.0,
            "UZK": 0.1,
            "PCTIM": 0.0,
            "ADIMP": 0.0,
            "RIVA": 0.0,
            "ZPERC": 1.0,
            "REXP": 1.0,
            "LZTWM": 5.0,
            "LZFSM": 5.0,
            "LZFPM": 5.0,
            "LZSK": 0.01,
            "LZPK": 0.0001,
            "PFREE": 0.0,
            "SIDE": 0.0,
            "RSERV": 0.0,
        },
        {
            "UZTWM": 150.0,
            "UZFWM": 150.0,
            "UZK": 0.5,
            "PCTIM": 0.1,
            "ADIMP": 0.4,
            "RIVA": 0.1,
            "ZPERC": 250.0,
            "REXP": 3.0,
            "LZTWM": 400.0,
            "LZFSM": 300.0,
            "LZFPM": 500.0,
            "LZSK": 0.35,
            "LZPK": 0.05,
            "PFREE": 0.6,
            "SIDE": 0.5,
            "RSERV": 0.4,
        },
    )
    for p in extremes:
        q = simulate(_scheme(p), _basin(), _forcing(precip, pet), include_warmup=True)
        assert np.isfinite(q).all() and (q >= 0).all()


def test_side_bypass_and_direct_runoff_component_signing():
    params = dict(REFERENCE_PARAMS)
    days = 60
    precip = np.zeros(days)
    precip[5] = 40.0
    pet = np.zeros(days)
    components = _components(_run_sma_day, precip, pet, params)
    assert (components["BFNCC"] >= 0).all()
    assert (components["SSUR"] >= 0).all()
    assert (components["SDRO"] >= 0).all()
    assert float(components["TCI"].sum()) > 0.0
