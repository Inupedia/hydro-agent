"""US open-basin DEM delineate (pyflwdir) — no equal-area fake units."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydro_agent.modeling.basins import BasinCatalog
from hydro_agent.modeling.us_plans import UsModelPlanService, UsPlanRequest

LEAF = Path(__file__).resolve().parents[2] / "data" / "basins" / "usgs_02472000"


pytestmark = pytest.mark.skipif(
    not (LEAF / "dem" / "sources.json").is_file() or not (LEAF / "gis" / "boundary.geojson").is_file(),
    reason="local Leaf River DEM/GIS fixtures required",
)


def test_delineate_open_basin_writes_real_units(tmp_path: Path):
    pytest.importorskip("pyflwdir")
    pytest.importorskip("rasterio")

    from hydro_agent.modeling.us_delineate import delineate_open_basin

    case = tmp_path / "case"
    result = delineate_open_basin(
        dem_dir=LEAF / "dem",
        source_gis=LEAF / "gis",
        case_dir=case,
        resolution_m=180,  # coarser for CI/local speed
        stream_area_km2=80,
        unit_area_km2=120,
        snap_distance_m=3000,
        min_iou=0.55,
        model_mode="distributed",
    )
    assert result["unit_count"] >= 2
    assert (case / "gis" / "units.geojson").is_file()
    assert (case / "gis" / "units.tif").is_file()
    assert (case / "gis" / "unit_topology.json").is_file()
    units = json.loads((case / "gis" / "units.geojson").read_text(encoding="utf-8"))
    unit_ids = {int(f["properties"]["unit_id"]) for f in units["features"]}
    assert unit_ids == set(range(1, result["unit_count"] + 1))
    assert result["boundary_check"]["accepted"] is True
    assert "equal-area" not in json.dumps(result["dem_config"]).lower()
    assert "subbasins_area" in result["dem_config"]["partition_method"]


def test_us_distributed_plan_rejects_without_dem(tmp_path: Path):
    catalog = BasinCatalog(tmp_path / "basins", academy=tmp_path / "academy")
    hydro = catalog.hydro_dir("usgs_02472000")
    hydro.mkdir(parents=True)
    (hydro / "forcing.jsonl").write_text("{}\n", encoding="utf-8")
    (hydro / "flow.jsonl").write_text("{}\n", encoding="utf-8")
    service = UsModelPlanService(tmp_path / "plans", catalog)
    with pytest.raises(ValueError, match="DEM"):
        service.create(
            UsPlanRequest(basin_id="usgs_02472000", model_mode="distributed", warmup_days=1)
        )
    service.pool.shutdown(wait=False)
