"""HBV-light reference parity and numerical stress gates for source_verified unlock."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from hydro_agent.models.hbv.contracts import HbvBasin, HbvScheme
from hydro_agent.models.hbv.engine import maxbas_triangle_weights, simulate, simulate_diagnostics
from hydro_agent.models.hbv.parity import (
    PARITY_ABS_MM_DAY,
    REFERENCE_ORACLE,
    REFERENCE_PARAMS,
)
from hydro_agent.models.hbv.reference_oracle import maxbas_weights, simulate_reference
from hydro_agent.models.registry import default_model_registry

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "hbv"
PARITY_NPZ = FIXTURES / "hydromad_parity_series.npz"
PARITY_META = FIXTURES / "hydromad_parity_meta.json"


def _scheme(params: dict[str, float] | None = None, *, warmup_days: int = 1) -> HbvScheme:
    return HbvScheme(
        warmup_days=warmup_days,
        parameters=dict(params or REFERENCE_PARAMS),
    )


def _basin(area_km2: float = 1.0) -> HbvBasin:
    return HbvBasin(basin_id="hbv-parity", area_km2=area_km2)


def _forcing(precip, temperature, pet) -> np.ndarray:
    precip = np.asarray(precip, dtype=float)
    temperature = np.asarray(temperature, dtype=float)
    pet = np.asarray(pet, dtype=float)
    return np.stack([precip, temperature, pet], axis=-1)[:, None, :]


def test_hbv_plugin_is_source_verified_for_product_calibration():
    descriptor = default_model_registry().get("hbv").descriptor
    assert descriptor.validation_status == "source_verified"
    assert descriptor.supports_calibration is True
    assert REFERENCE_ORACLE in (descriptor.technical_reference or "")


def test_registered_parity_thresholds_cover_oracle_outputs():
    meta = json.loads(PARITY_META.read_text(encoding="utf-8"))
    assert meta["oracle"] == REFERENCE_ORACLE
    assert set(meta["thresholds_mm_day"]) == set(PARITY_ABS_MM_DAY)
    for key, value in PARITY_ABS_MM_DAY.items():
        assert meta["thresholds_mm_day"][key] == value


def test_maxbas_weights_match_analytic_triangle_integral():
    for maxbas in (1.0, 1.7, 2.5, 3.0, 5.25):
        product = np.asarray(maxbas_triangle_weights(maxbas), dtype=float)
        # Oracle stores reversed rollapplyr weights; product uses same-day-first.
        oracle = maxbas_weights(maxbas)[::-1]
        assert product.shape == oracle.shape
        assert np.allclose(product, oracle, atol=1e-12, rtol=0.0)
        assert abs(float(product.sum()) - 1.0) < 1e-12


def test_uzl_suppresses_quickflow_below_threshold():
    days = 40
    # Keep soil nearly full so recharge reaches SUZ, but UZL high enough that Q0=0.
    params = {**REFERENCE_PARAMS, "UZL": 500.0, "K0": 0.4, "MAXBAS": 1.0, "PERC": 0.0}
    precip = np.full(days, 6.0)
    temp = np.full(days, 8.0)
    pet = np.full(days, 0.5)
    series = simulate_diagnostics(
        _scheme(params), _basin(), _forcing(precip, temp, pet), include_warmup=True
    )
    assert np.allclose(series["Q0"], 0.0, atol=1e-12)


def test_sfcf_scales_snowfall_accumulation():
    days = 20
    precip = np.full(days, 5.0)
    temp = np.full(days, -2.0)
    pet = np.full(days, 0.2)
    low = simulate_diagnostics(
        _scheme({**REFERENCE_PARAMS, "SFCF": 0.5, "MAXBAS": 1.0}),
        _basin(),
        _forcing(precip, temp, pet),
        include_warmup=True,
    )
    high = simulate_diagnostics(
        _scheme({**REFERENCE_PARAMS, "SFCF": 1.0, "MAXBAS": 1.0}),
        _basin(),
        _forcing(precip, temp, pet),
        include_warmup=True,
    )
    assert float(high["Snow"][-1]) > float(low["Snow"][-1])


def test_daily_state_and_discharge_parity_against_frozen_hydromad_fixture():
    data = np.load(PARITY_NPZ)
    inputs = _forcing(data["P"], data["T"], data["E"])
    ours = simulate_diagnostics(_scheme(), _basin(), inputs, include_warmup=True)
    for key, limit in PARITY_ABS_MM_DAY.items():
        residual = ours[key] - data[key]
        max_abs = float(np.max(np.abs(residual)))
        assert max_abs <= limit, f"{key} max |Δ|={max_abs} exceeds registered {limit}"


def test_live_reference_oracle_matches_engine():
    data = np.load(PARITY_NPZ)
    ref = simulate_reference(data["P"], data["T"], data["E"], REFERENCE_PARAMS)
    ours = simulate_diagnostics(
        _scheme(), _basin(), _forcing(data["P"], data["T"], data["E"]), include_warmup=True
    )
    for key, limit in PARITY_ABS_MM_DAY.items():
        residual = ours[key] - ref[key]
        max_abs = float(np.max(np.abs(residual)))
        assert max_abs <= limit, f"{key} live |Δ|={max_abs} exceeds registered {limit}"


def test_zero_precipitation_drains_without_negative_runoff():
    days = 120
    inputs = _forcing(np.zeros(days), np.full(days, 5.0), np.full(days, 2.0))
    series = simulate_diagnostics(_scheme(), _basin(), inputs, include_warmup=True)
    assert np.all(series["Qsim"] >= 0.0)
    assert series["SM"][-1] < series["SM"][0]


def test_constant_precipitation_keeps_finite_mass_balance():
    days = 400
    precip = 5.0
    inputs = _forcing(np.full(days, precip), np.full(days, 6.0), np.full(days, 1.0))
    series = simulate_diagnostics(_scheme(), _basin(), inputs, include_warmup=True)
    runoff = float(series["Qsim"].sum())
    initial = REFERENCE_PARAMS["FC"] * REFERENCE_PARAMS["LP"]
    final = float(series["SM"][-1] + series["SUZ"][-1] + series["SLZ"][-1] + series["Snow"][-1])
    assert runoff + final <= days * precip + initial + 1e-4


def test_soil_parameter_has_continuous_identifiable_effect():
    days = 60
    inputs = _forcing(np.full(days, 8.0), np.full(days, 6.0), np.full(days, 2.0))
    base = dict(REFERENCE_PARAMS)
    low = simulate(_scheme({**base, "FC": 80.0}), _basin(), inputs, include_warmup=True)
    high = simulate(_scheme({**base, "FC": 400.0}), _basin(), inputs, include_warmup=True)
    assert not np.allclose(low, high)
    assert np.isfinite(low).all() and np.isfinite(high).all()
    assert abs(float(low.sum() - high.sum())) > 1e-6


def test_extreme_parameters_remain_finite_and_nonnegative():
    days = 90
    inputs = _forcing(
        np.linspace(0.0, 80.0, days),
        np.linspace(-5.0, 15.0, days),
        np.full(days, 3.0),
    )
    extremes = (
        {
            **REFERENCE_PARAMS,
            "TT": -2.5,
            "CFMAX": 1.0,
            "SFCF": 0.4,
            "FC": 50.0,
            "BETA": 1.0,
            "LP": 0.3,
            "K0": 0.05,
            "K1": 0.01,
            "K2": 0.001,
            "PERC": 0.0,
            "UZL": 0.0,
            "MAXBAS": 1.0,
        },
        {
            **REFERENCE_PARAMS,
            "TT": 2.5,
            "CFMAX": 10.0,
            "SFCF": 1.0,
            "FC": 500.0,
            "BETA": 6.0,
            "LP": 1.0,
            "K0": 0.5,
            "K1": 0.3,
            "K2": 0.1,
            "PERC": 3.0,
            "UZL": 100.0,
            "MAXBAS": 7.0,
        },
    )
    for params in extremes:
        q = simulate(_scheme(params), _basin(area_km2=250.0), inputs, include_warmup=True)
        assert np.isfinite(q).all()
        assert (q >= 0.0).all()


def test_segmented_resume_matches_continuous_run():
    days = 80
    precip = np.concatenate([np.zeros(20), np.array([10.0, 25.0, 8.0]), np.zeros(57)])
    temp = np.concatenate([np.full(30, -1.0), np.full(50, 6.0)])
    pet = np.full(days, 1.5)
    inputs = _forcing(precip, temp, pet)
    continuous = simulate_diagnostics(_scheme(warmup_days=1), _basin(), inputs, include_warmup=True)

    split = 40
    first = simulate_diagnostics(
        _scheme(warmup_days=1), _basin(), inputs[:split], include_warmup=True
    )
    end = first["StateEnd"]
    resumed = simulate_diagnostics(
        _scheme(warmup_days=1),
        _basin(),
        inputs[split:],
        include_warmup=True,
        init_snow=end["snow"],
        init_liquid=end["liquid"],
        init_soil=end["soil"],
        init_suz=end["suz"],
        init_slz=end["slz"],
        init_delay=end["delay"],
    )
    assert np.allclose(continuous["Qsim"][:split], first["Qsim"], atol=0.0, rtol=0.0)
    assert np.allclose(continuous["Qsim"][split:], resumed["Qsim"], atol=0.0, rtol=0.0)
    assert np.allclose(continuous["SM"][split:], resumed["SM"], atol=0.0, rtol=0.0)
    assert np.allclose(continuous["SUZ"][split:], resumed["SUZ"], atol=0.0, rtol=0.0)
