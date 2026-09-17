"""Tank 3-tank + discrete Nash reference parity and numerical stress gates."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydro_agent.models.registry import default_model_registry
from hydro_agent.models.tank.contracts import TankBasin, TankScheme
from hydro_agent.models.tank.engine import simulate, simulate_diagnostics
from hydro_agent.models.tank.param_groups import snap_discrete_parameters
from hydro_agent.models.tank.parity import (
    PARITY_ABS_MM_DAY,
    REFERENCE_ORACLE,
    REFERENCE_PARAMS,
)
from hydro_agent.models.tank.reference_oracle import simulate_reference

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "tank"
PARITY_NPZ = FIXTURES / "sugawara_parity_series.npz"
PARITY_META = FIXTURES / "sugawara_parity_meta.json"


def _scheme(params: dict[str, float] | None = None, *, warmup_days: int = 1) -> TankScheme:
    return TankScheme(
        warmup_days=warmup_days,
        parameters=snap_discrete_parameters(dict(params or REFERENCE_PARAMS)),
    )


def _basin(area_km2: float = 1.0) -> TankBasin:
    return TankBasin(basin_id="tank-parity", area_km2=area_km2)


def _forcing(precip, pet) -> np.ndarray:
    precip = np.asarray(precip, dtype=float)
    pet = np.asarray(pet, dtype=float)
    return np.stack([precip, pet], axis=-1)[:, None, :]


def test_tank_plugin_is_source_verified_for_product_calibration():
    descriptor = default_model_registry().get("tank").descriptor
    assert descriptor.validation_status == "source_verified"
    assert descriptor.supports_calibration is True
    assert REFERENCE_ORACLE in (descriptor.technical_reference or "")


def test_registered_parity_thresholds_cover_oracle_outputs():
    meta = json.loads(PARITY_META.read_text(encoding="utf-8"))
    assert meta["oracle"] == REFERENCE_ORACLE
    assert set(meta["thresholds_mm_day"]) == set(PARITY_ABS_MM_DAY)


def test_n_is_snapped_to_integer_before_evaluation():
    plugin = default_model_registry().get("tank")
    snapped = plugin.canonicalize_parameters({**REFERENCE_PARAMS, "N": 2.6})
    assert snapped["N"] == 3.0
    with pytest.raises(ValueError):
        TankScheme(warmup_days=1, parameters={**REFERENCE_PARAMS, "N": 2.6})


def test_daily_state_and_discharge_parity_against_frozen_fixture():
    data = np.load(PARITY_NPZ)
    inputs = _forcing(data["P"], data["E"])
    ours = simulate_diagnostics(_scheme(), _basin(), inputs, include_warmup=True)
    for key, limit in PARITY_ABS_MM_DAY.items():
        residual = ours[key] - data[key]
        max_abs = float(np.max(np.abs(residual)))
        assert max_abs <= limit, f"{key} max |Δ|={max_abs} exceeds registered {limit}"


def test_live_reference_oracle_matches_engine():
    data = np.load(PARITY_NPZ)
    ref = simulate_reference(data["P"], data["E"], REFERENCE_PARAMS)
    ours = simulate_diagnostics(
        _scheme(), _basin(), _forcing(data["P"], data["E"]), include_warmup=True
    )
    for key, limit in PARITY_ABS_MM_DAY.items():
        residual = ours[key] - ref[key]
        max_abs = float(np.max(np.abs(residual)))
        assert max_abs <= limit, f"{key} live |Δ|={max_abs} exceeds registered {limit}"


def test_zero_precipitation_drains_without_negative_runoff():
    days = 120
    inputs = _forcing(np.zeros(days), np.full(days, 2.0))
    series = simulate_diagnostics(_scheme(), _basin(), inputs, include_warmup=True)
    assert np.all(series["Qsim"] >= 0.0)
    assert series["S1"][-1] < series["S1"][0]


def test_constant_precipitation_keeps_finite_mass_balance():
    days = 400
    precip = 5.0
    inputs = _forcing(np.full(days, precip), np.full(days, 1.0))
    series = simulate_diagnostics(_scheme(), _basin(), inputs, include_warmup=True)
    runoff = float(series["Qsim"].sum())
    et = float(series["ET"].sum())
    final = float(series["S1"][-1] + series["S2"][-1] + series["S3"][-1])
    initial = 10.0 + 10.0 + 20.0
    assert runoff + et + final <= days * precip + initial + 1e-4


def test_surface_parameter_has_continuous_identifiable_effect():
    days = 60
    inputs = _forcing(np.full(days, 8.0), np.full(days, 2.0))
    low = simulate(_scheme({**REFERENCE_PARAMS, "H1": 5.0}), _basin(), inputs, include_warmup=True)
    high = simulate(_scheme({**REFERENCE_PARAMS, "H1": 40.0}), _basin(), inputs, include_warmup=True)
    assert not np.allclose(low, high)
    assert abs(float(low.sum() - high.sum())) > 1e-6


def test_discrete_nash_length_changes_routing():
    days = 40
    inputs = _forcing(np.concatenate([np.zeros(5), [20.0], np.zeros(34)]), np.full(days, 1.0))
    n1 = simulate(_scheme({**REFERENCE_PARAMS, "N": 1.0}), _basin(), inputs, include_warmup=True)
    n5 = simulate(_scheme({**REFERENCE_PARAMS, "N": 5.0}), _basin(), inputs, include_warmup=True)
    assert not np.allclose(n1, n5)
    # Longer cascade delays and attenuates the peak.
    assert float(np.max(n5)) < float(np.max(n1)) + 1e-9


def test_extreme_parameters_remain_finite_and_nonnegative():
    days = 90
    inputs = _forcing(np.linspace(0.0, 80.0, days), np.full(days, 3.0))
    extremes = (
        {
            **REFERENCE_PARAMS,
            "H1": 0.0,
            "A11": 0.05,
            "A12": 0.01,
            "B1": 0.05,
            "H2": 0.0,
            "A2": 0.01,
            "B2": 0.01,
            "A3": 0.001,
            "K": 0.1,
            "N": 1.0,
        },
        {
            **REFERENCE_PARAMS,
            "H1": 80.0,
            "A11": 0.5,
            "A12": 0.3,
            "B1": 0.5,
            "H2": 40.0,
            "A2": 0.3,
            "B2": 0.3,
            "A3": 0.1,
            "K": 0.8,
            "N": 5.0,
        },
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
    end = first["StateEnd"]
    resumed = simulate_diagnostics(
        _scheme(warmup_days=1),
        _basin(),
        inputs[split:],
        include_warmup=True,
        init_s1=end["s1"],
        init_s2=end["s2"],
        init_s3=end["s3"],
        init_nash=end["nash"],
    )
    assert np.allclose(continuous["Qsim"][:split], first["Qsim"], atol=0.0, rtol=0.0)
    assert np.allclose(continuous["Qsim"][split:], resumed["Qsim"], atol=0.0, rtol=0.0)
    assert np.allclose(continuous["S1"][split:], resumed["S1"], atol=0.0, rtol=0.0)
