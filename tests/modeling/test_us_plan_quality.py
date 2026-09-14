from __future__ import annotations

import csv
import json
from datetime import date, timedelta

from hydro_agent.data.lowman import load_normalized_source
from hydro_agent.modeling.basins import BasinCatalog
from hydro_agent.modeling.plans import write_json
from hydro_agent.modeling.us_plans import UsModelPlanService, UsPlanRequest


def _write_jsonl(path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_us_model_plan_preserves_imputed_flow_quality_end_to_end(tmp_path):
    catalog = BasinCatalog(tmp_path / "basins", academy=tmp_path / "academy")
    hydro = catalog.hydro_dir("usgs_02472000")
    hydro.mkdir(parents=True, exist_ok=True)

    start = date(2016, 9, 1)
    days = 90
    imputed_day = date(2016, 11, 27)
    forcing = []
    flow = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        stamp = day.isoformat()
        forcing.append(
            {
                "valid_date": stamp,
                "available_at": f"{stamp}T23:59:59+00:00",
                "source": "gridmet:test",
                "precipitation_mm_day": 5.0,
                "pet_mm_day": 2.0,
            }
        )
        is_imputed = day == imputed_day
        flow.append(
            {
                "valid_date": stamp,
                "available_at": f"{stamp}T23:59:59+00:00",
                "source": "usgs:nwis:02472000",
                "discharge_m3s": 12.5,
                "eligible_for_scoring": not is_imputed,
                "quality_code": "imputed" if is_imputed else "approved",
                "quality_note": "gap-filled for continuity" if is_imputed else "observed",
            }
        )

    _write_jsonl(hydro / "forcing.jsonl", forcing)
    _write_jsonl(hydro / "flow.jsonl", flow)
    write_json(hydro / "basin.json", {"basin_id": "usgs_02472000", "area_km2": 1944.0})

    service = UsModelPlanService(tmp_path / "plans", catalog)
    try:
        plan_id = "plan-quality-test"
        plan_dir = service.directory(plan_id)
        (plan_dir / "case" / "gis").mkdir(parents=True)
        write_json(
            plan_dir / "plan.json",
            {"plan_id": plan_id, "basin_id": "usgs_02472000", "status": "running"},
        )
        with (plan_dir / "case" / "gis" / "units.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=["unit_id", "area_km2", "source"])
            writer.writeheader()
            writer.writerow({"unit_id": 1, "area_km2": 1944.0, "source": "full-basin"})

        cfg = UsPlanRequest(basin_id="usgs_02472000", warmup_days=1)
        service._build_inputs(plan_id, cfg)
        service._normalize(plan_id, cfg)

        with (plan_dir / "case" / "model_inputs" / "observed.csv").open(
            encoding="utf-8"
        ) as handle:
            observed = {row["time"]: row for row in csv.DictReader(handle)}
        raw_product_row = observed[imputed_day.isoformat()]
        assert raw_product_row["eligible_for_scoring"] == "false"
        assert raw_product_row["quality_code"] == "imputed"
        assert raw_product_row["source"] == "usgs:nwis:02472000"

        normalized = load_normalized_source(plan_dir / "normalized")
        normalized_row = next(row for row in normalized.flow_rows if row.valid_date == imputed_day)
        assert normalized_row.eligible_for_scoring is False
        assert normalized_row.quality_code == "imputed"
        assert normalized_row.quality_note == "gap-filled for continuity"
        assert normalized_row.source == "usgs:nwis:02472000"
    finally:
        service.pool.shutdown(wait=False, cancel_futures=True)
