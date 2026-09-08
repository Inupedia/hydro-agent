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
