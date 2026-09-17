"""GR4J reference parity and numerical stress gates for source_verified unlock."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydro_agent.models.gr4j.contracts import Gr4jBasin, Gr4jScheme
from hydro_agent.models.gr4j.engine import simulate, simulate_diagnostics
from hydro_agent.models.gr4j.parity import (
    PARITY_ABS_MM_DAY,
    REFERENCE_ORACLE,
    REFERENCE_PARAMS,
)
from hydro_agent.models.registry import default_model_registry

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "gr4j"
PARITY_NPZ = FIXTURES / "airgr_parity_series.npz"
PARITY_META = FIXTURES / "airgr_parity_meta.json"


def _scheme(params: dict[str, float] | None = None, *, warmup_days: int = 1) -> Gr4jScheme:
    return Gr4jScheme(
        warmup_days=warmup_days,
        parameters=dict(params or REFERENCE_PARAMS),
    )


def _basin(area_km2: float = 1.0) -> Gr4jBasin:
    return Gr4jBasin(basin_id="gr4j-parity", area_km2=area_km2)


def _forcing(precip, pet) -> np.ndarray:
    precip = np.asarray(precip, dtype=float)
    pet = np.asarray(pet, dtype=float)
    return np.stack([precip, pet], axis=-1)[:, None, :]


def test_gr4j_plugin_is_source_verified_for_product_calibration():
    descriptor = default_model_registry().get("gr4j").descriptor
    assert descriptor.validation_status == "source_verified"
    assert descriptor.supports_calibration is True
    assert REFERENCE_ORACLE in (descriptor.technical_reference or "")


def test_registered_parity_thresholds_cover_airgr_outputs():
    meta = json.loads(PARITY_META.read_text(encoding="utf-8"))
    assert meta["oracle"] == REFERENCE_ORACLE
    assert set(meta["thresholds_mm_day"]) == set(PARITY_ABS_MM_DAY)
    for key, value in PARITY_ABS_MM_DAY.items():
        assert meta["thresholds_mm_day"][key] == value


def test_daily_state_and_discharge_parity_against_frozen_airgr_fixture():
    data = np.load(PARITY_NPZ)
    inputs = _forcing(data["P"], data["E"])
    ours = simulate_diagnostics(_scheme(), _basin(), inputs, include_warmup=True)
    for key, limit in PARITY_ABS_MM_DAY.items():
        residual = ours[key] - data[key]
        max_abs = float(np.max(np.abs(residual)))
        assert max_abs <= limit, f"{key} max |Δ|={max_abs} exceeds registered {limit}"


def test_zero_precipitation_drains_without_negative_runoff():
    days = 120
    inputs = _forcing(np.zeros(days), np.full(days, 2.0))
    series = simulate_diagnostics(_scheme(), _basin(), inputs, include_warmup=True)
    assert np.all(series["Qsim"] >= 0.0)
    assert series["Prod"][-1] < series["Prod"][0]
    assert float(series["Qsim"][-1]) < float(series["Qsim"][0])


def test_constant_precipitation_conserves_water_with_zero_exchange():
    days = 400
    precip = 5.0
    inputs = _forcing(np.full(days, precip), np.full(days, 1.0))
    params = {**REFERENCE_PARAMS, "X2": 0.0}
    series = simulate_diagnostics(_scheme(params), _basin(), inputs, include_warmup=True)
    runoff = float(series["Qsim"].sum())
    initial = 0.3 * params["X1"] + 0.5 * params["X3"]
    final = float(series["Prod"][-1] + series["Rout"][-1])
    # Stores + runoff cannot invent water beyond precip + initial storage.
    assert runoff + final <= days * precip + initial + 1e-6


def test_production_parameter_has_continuous_identifiable_effect():
    days = 60
    inputs = _forcing(np.full(days, 8.0), np.full(days, 2.0))
    base = dict(REFERENCE_PARAMS)
    low = simulate(
        _scheme({**base, "X1": 200.0}), _basin(), inputs, include_warmup=True
    )
    high = simulate(
        _scheme({**base, "X1": 800.0}), _basin(), inputs, include_warmup=True
    )
    assert not np.allclose(low, high)
    # Larger production capacity should not produce NaNs and should change volume.
    assert np.isfinite(low).all() and np.isfinite(high).all()
    assert abs(float(low.sum() - high.sum())) > 1e-6


def test_extreme_parameters_remain_finite_and_nonnegative():
    days = 90
    inputs = _forcing(np.linspace(0.0, 80.0, days), np.full(days, 3.0))
    extremes = (
        {"X1": 1.0, "X2": -50.0, "X3": 1.0, "X4": 0.5},
        {"X1": 5000.0, "X2": 50.0, "X3": 500.0, "X4": 5.0},
    )
    for params in extremes:
        q = simulate(_scheme(params), _basin(area_km2=250.0), inputs, include_warmup=True)
        assert np.isfinite(q).all()
        assert (q >= 0.0).all()


def test_segmented_resume_matches_continuous_run():
    days = 80
    precip = np.concatenate([np.zeros(20), np.array([10.0, 25.0, 8.0]), np.zeros(57)])
    pet = np.full(days, 1.5)
    inputs = _forcing(precip, pet)
    continuous = simulate_diagnostics(_scheme(warmup_days=1), _basin(), inputs, include_warmup=True)

    split = 40
    first = simulate_diagnostics(
        _scheme(warmup_days=1), _basin(), inputs[:split], include_warmup=True
    )
    resumed = simulate_diagnostics(
        _scheme(warmup_days=1),
        _basin(),
        inputs[split:],
        include_warmup=True,
        init_production=first["StateEnd"]["production"],
        init_routing=first["StateEnd"]["routing"],
        init_uh1=first["StateEnd"]["uh1"],
        init_uh2=first["StateEnd"]["uh2"],
    )
    assert np.allclose(continuous["Qsim"][:split], first["Qsim"], atol=0.0, rtol=0.0)
    assert np.allclose(continuous["Qsim"][split:], resumed["Qsim"], atol=0.0, rtol=0.0)
    assert np.allclose(continuous["Prod"][split:], resumed["Prod"], atol=0.0, rtol=0.0)
    assert np.allclose(continuous["Rout"][split:], resumed["Rout"], atol=0.0, rtol=0.0)


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("grsuite") is None,
    reason="optional live oracle; frozen fixture covers CI",
)
def test_live_grsuite_oracle_still_matches_when_installed():
    import grsuite as gr

    data = np.load(PARITY_NPZ)
    n = int(data["P"].shape[0])
    dates = np.arange("2001-01-01", n, dtype="datetime64[D]")
    param = np.array([REFERENCE_PARAMS[k] for k in ("X1", "X2", "X3", "X4")], dtype=float)
    inputs = gr.InputsModel(dates, precip=data["P"], pot_evap=data["E"])
    opts = gr.RunOptions(
        inputs,
        "GR4J",
        ind_period_run=np.arange(n),
        ind_period_warmup=np.array([], dtype=int),
    )
    live = gr.MODEL_FUNCS["GR4J"](inputs, opts, param)
    for key, limit in PARITY_ABS_MM_DAY.items():
        residual = np.asarray(live[key], dtype=float) - data[key]
        assert float(np.max(np.abs(residual))) <= limit
