import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from hydro_agent.models.xaj.conversion import load_xaj_inputs, runoff_mm_day_to_m3s

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "xaj"


def test_runoff_depth_conversion():
    # 1 mm/day over 1 km² = 1000 m³/day
    assert runoff_mm_day_to_m3s(1.0, 1.0) == pytest.approx(1000.0 / 86400.0)


def test_load_xaj_inputs_requires_exact_forcing_columns(tmp_path):
    pytest.importorskip("numpy")
    workspace = _workspace(tmp_path)
    scheme, basin, dates, p_and_e = load_xaj_inputs(workspace)
    assert basin.basin_id == "camels_13235000"
    assert dates[0] == date(2025, 12, 28)
    assert dates[-1] == date(2026, 1, 4)
    assert len(dates) >= scheme.warmup_days + 3
    assert p_and_e.shape == (len(dates), 1, 2)
    assert (p_and_e >= 0).all()


def test_load_xaj_inputs_supports_distributed_unit_forcing(tmp_path):
    pytest.importorskip("numpy")
    workspace = _workspace(tmp_path)
    scheme_path = workspace / "input/scheme/scheme.json"
    payload = json.loads(scheme_path.read_text(encoding="utf-8"))
    payload["units"] = [
        {"unit_id": 1, "area_km2": 592.0, "centroid_lon": -115.7, "centroid_lat": 44.1},
        {"unit_id": 2, "area_km2": 592.0, "centroid_lon": -115.5, "centroid_lat": 44.0},
    ]
    scheme_path.write_text(json.dumps(payload), encoding="utf-8")
    (workspace / "input/snapshot/forcing.csv").write_text(
        "\n".join(
            [
                "date,unit_1_precipitation_mm_day,unit_1_pet_mm_day,unit_2_precipitation_mm_day,unit_2_pet_mm_day",
                "2025-12-28,1.0,0.5,1.2,0.4",
                "2025-12-29,2.0,0.6,2.2,0.5",
                "2025-12-30,0.0,0.7,0.2,0.6",
                "2025-12-31,3.0,0.8,3.2,0.7",
                "2026-01-01,1.5,0.9,1.7,0.8",
                "2026-01-02,4.0,1.0,4.2,0.9",
                "2026-01-03,0.5,1.1,0.7,1.0",
                "2026-01-04,2.5,1.2,2.7,1.1",
                "",
            ]
        ),
        encoding="utf-8",
    )

    scheme, _basin, dates, p_and_e = load_xaj_inputs(workspace)

    assert tuple(unit.unit_id for unit in scheme.units) == (1, 2)
    assert p_and_e.shape == (len(dates), 2, 2)
    assert p_and_e[0, 0].tolist() == pytest.approx([1.0, 0.5])
    assert p_and_e[0, 1].tolist() == pytest.approx([1.2, 0.4])


def test_load_xaj_inputs_rejects_wrong_columns(tmp_path):
    pytest.importorskip("numpy")
    workspace = _workspace(tmp_path)
    (workspace / "input/snapshot/forcing.csv").write_text(
        "date,precip,pet\n2025-12-28,1,1\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="invalid forcing columns"):
        load_xaj_inputs(workspace)


def _workspace(tmp_path: Path) -> Path:
    snapshot = tmp_path / "input" / "snapshot"
    scheme = tmp_path / "input" / "scheme"
    snapshot.mkdir(parents=True)
    scheme.mkdir(parents=True)
    shutil.copy(FIXTURES / "forcing.csv", snapshot / "forcing.csv")
    shutil.copy(FIXTURES / "basin.json", snapshot / "basin.json")
    shutil.copy(FIXTURES / "scheme.json", scheme / "scheme.json")
    return tmp_path
