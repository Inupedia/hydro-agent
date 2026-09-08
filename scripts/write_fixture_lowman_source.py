#!/usr/bin/env python3
"""Write a tiny reanalysis-only Lowman-like source for F-mode rejection tests."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from hydro_agent.data.contracts import FlowObservation, ForcingRow

PUBLISHED = datetime(2024, 6, 1, tzinfo=timezone.utc)
START = date(2020, 4, 28)
BASIN = {
    "basin_id": "camels_13235000",
    "station_id": "USGS-13235000",
    "area_km2": 1184.0,
    "day_timezone": "UTC",
}


def write_source(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    forcing = []
    flow = []
    for i in range(10):
        day = START + timedelta(days=i)
        forcing.append(
            ForcingRow(
                valid_date=day,
                precipitation_mm_day=1.0 + i * 0.1,
                pet_mm_day=2.0,
                source_kind="reanalysis",
                source="caravan-era5-land-fao-pm",
                available_at=PUBLISHED,
            )
        )
        flow.append(
            FlowObservation(
                valid_date=day,
                discharge_m3s=5.0 + i,
                source="caravan-streamflow",
                available_at=PUBLISHED,
            )
        )
    (output / "forcing.jsonl").write_text(
        "\n".join(r.model_dump_json() for r in forcing) + "\n", encoding="utf-8"
    )
    (output / "flow.jsonl").write_text(
        "\n".join(r.model_dump_json() for r in flow) + "\n", encoding="utf-8"
    )
    (output / "basin.json").write_text(json.dumps(BASIN, sort_keys=True), encoding="utf-8")
    return output


if __name__ == "__main__":
    path = write_source(Path("tests/fixtures/lowman_reanalysis_source"))
    print(path.resolve())
