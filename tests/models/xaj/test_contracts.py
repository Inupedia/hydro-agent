import pytest
from pydantic import ValidationError

from hydro_agent.models.xaj.contracts import XajBasin, XajScheme

PARAMS = {
    "K": 0.75,
    "B": 0.25,
    "IM": 0.06,
    "UM": 20.0,
    "LM": 60.0,
    "DM": 40.0,
    "C": 0.16,
    "SM": 20.0,
    "EX": 1.2,
    "KI": 0.3,
    "KG": 0.4,
    "CS": 0.9,
    "L": 2.0,
    "CI": 0.8,
    "CG": 0.98,
}


def test_xaj_scheme_requires_exact_parameter_set():
    scheme = XajScheme(model_id="xaj", warmup_days=365, parameters=PARAMS)
    assert list(scheme.parameter_vector()) == [PARAMS[name] for name in scheme.PARAMETER_ORDER]
    broken = dict(PARAMS)
    broken.pop("KG")
    with pytest.raises(ValidationError):
        XajScheme(model_id="xaj", warmup_days=365, parameters=broken)


def test_exact_order():
    scheme = XajScheme(parameters=PARAMS, warmup_days=365)
    assert scheme.parameter_vector() == tuple(PARAMS.values())


def test_xaj_basin_requires_positive_area():
    basin = XajBasin(basin_id="camels_13235000", area_km2=1184.0)
    assert basin.area_km2 == 1184.0
    with pytest.raises(ValidationError):
        XajBasin(basin_id="camels_13235000", area_km2=0)


@pytest.mark.parametrize(
    "change", [{"KG": None}, {"K": float("nan")}, {"K": -1}, {"KI": 0.7}, {"L": 1.5}]
)
def test_invalid_parameters(change):
    with pytest.raises(ValidationError):
        XajScheme(parameters=PARAMS | change, warmup_days=365)


def test_missing_parameter():
    with pytest.raises(ValidationError):
        XajScheme(parameters={k: v for k, v in PARAMS.items() if k != "KG"}, warmup_days=365)
