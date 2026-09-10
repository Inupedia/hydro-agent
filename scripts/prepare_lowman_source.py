"""Download official MultiMet forcing and modern USGS daily flow for Lowman.

This ingestion command runs outside numerical workspaces. Raw bytes and hashes are
retained. No secret or LLM client is used. Static station area metadata is pinned to
the current USGS monitoring-location record so transient metadata-service outages do
not make the long-running scientific E2E irreproducible.
"""

import argparse
import json
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
from numcodecs import get_codec

from hydro_agent.data.contracts import FlowObservation, ForcingRow
from hydro_agent.execution.hashing import sha256_file

BASE = "https://storage.googleapis.com/caravan-multimet/v1.1/ERA5_LAND/timeseries.zarr/"
USGS_DAILY = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/daily/items"
USGS_LOCATION_PAGE = "https://waterdata.usgs.gov/monitoring-location/USGS-13235000"
USGS_LOCATION_ID = "USGS-13235000"
USGS_SITE_NO = "13235000"
# Current official monitoring-location metadata for USGS-13235000 reports 446 mi².
LOWMAN_DRAINAGE_AREA_SQMI = 446.0
CFS_TO_M3S = 0.028316846592


def prepare(output, start, end):
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    receipts = []
    retrieved = datetime.now(timezone.utc)

    def download(url, name):
        destination = raw / name
        subprocess.run(
            [
                "curl",
                "-fsSL",
                "--retry",
                "6",
                "--retry-delay",
                "3",
                "--retry-all-errors",
                "--connect-timeout",
                "15",
                "--max-time",
                "120",
                url,
                "-o",
                str(destination),
            ],
            check=True,
        )
        receipts.append(
            dict(
                url=url,
                file="raw/" + name,
                sha256=sha256_file(destination),
                bytes=destination.stat().st_size,
                mode="downloaded",
            )
        )
        return destination.read_bytes()

    def pin_station_metadata():
        destination = raw / "usgs-site-pinned.json"
        payload = {
            "monitoring_location_id": USGS_LOCATION_ID,
            "monitoring_location_number": USGS_SITE_NO,
            "drainage_area": LOWMAN_DRAINAGE_AREA_SQMI,
            "drainage_area_unit": "square miles",
            "reference_url": USGS_LOCATION_PAGE,
            "note": "Pinned static metadata; dynamic discharge is downloaded from USGS Water Data API.",
        }
        destination.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        receipts.append(
            dict(
                url=USGS_LOCATION_PAGE,
                file="raw/usgs-site-pinned.json",
                sha256=sha256_file(destination),
                bytes=destination.stat().st_size,
                mode="pinned-reference",
            )
        )
        return payload

    metadata = json.loads(download(BASE + ".zmetadata", "zmetadata.json"))["metadata"]
    attrs = metadata[".zattrs"]
    if "FAO_PENMAN_MONTEITH" not in attrs.get("Units", ""):
        raise ValueError("FAO PM units metadata missing")

    def chunk(variable, key):
        info = metadata[variable + "/.zarray"]
        if info["filters"] is not None or info["order"] != "C":
            raise ValueError("unsupported Zarr layout")
        data = download(BASE + variable + "/" + key, variable + "-" + key + ".bin")
        decoded = get_codec(info["compressor"]).decode(data)
        return np.frombuffer(decoded, dtype=info["dtype"]).reshape(info["chunks"])

    basin_info = metadata["basin/.zarray"]
    basin_index = None
    for i in range(
        (basin_info["shape"][0] + basin_info["chunks"][0] - 1) // basin_info["chunks"][0]
    ):
        values = chunk("basin", str(i))
        matches = np.flatnonzero(values == "camels_13235000")
        if len(matches):
            basin_index = i * basin_info["chunks"][0] + int(matches[0])
            break
    if basin_index is None:
        raise ValueError("Lowman basin missing")
    date_attrs = metadata["date/.zattrs"]
    if date_attrs["units"] != "days since 1950-01-01 00:00:00":
        raise ValueError("unexpected date origin")
    dates = [date(1950, 1, 1) + timedelta(days=int(v)) for v in chunk("date", "0")]
    selected = [i for i, d in enumerate(dates) if start <= d <= end]
    if len(selected) != (end - start).days + 1:
        raise ValueError("incomplete source date coverage")
    series = {}
    for key in ("total_precipitation", "potential_evaporation_FAO_PENMAN_MONTEITH"):
        variable = "era5land_" + key
        info = metadata[variable + "/.zarray"]
        if info["chunks"][1] != len(dates):
            raise ValueError("unexpected time chunk layout")
        values = chunk(variable, f"{basin_index // info['chunks'][0]}.0")[
            basin_index % info["chunks"][0]
        ]
        series[key] = values[selected]

    station = pin_station_metadata()
    area_km2 = float(station["drainage_area"]) * 2.589988110336
    basin = dict(
        basin_id="camels_13235000",
        station_id=USGS_LOCATION_ID,
        area_km2=area_km2,
        day_timezone="UTC",
    )
    rows = []
    for j, i in enumerate(selected):
        rows.append(
            ForcingRow(
                valid_date=dates[i],
                precipitation_mm_day=float(series["total_precipitation"][j]),
                pet_mm_day=float(series["potential_evaporation_FAO_PENMAN_MONTEITH"][j]),
                source_kind="reanalysis",
                source="caravan-multimet-v1.1-era5-land-fao-pm",
                available_at=retrieved,
            )
        )
    (output / "forcing.jsonl").write_text(
        "\n".join(r.model_dump_json() for r in rows) + "\n", encoding="utf-8"
    )

    daily_url = (
        f"{USGS_DAILY}?f=json&limit=10000"
        f"&datetime={start.isoformat()}/{end.isoformat()}"
        f"&monitoring_location_id={USGS_LOCATION_ID}"
        "&parameter_code=00060&statistic_id=00003"
    )
    daily_payload = json.loads(download(daily_url, "usgs-daily-00060-00003.json"))
    features = list(daily_payload.get("features") or [])
    next_links = [
        link for link in daily_payload.get("links") or [] if str(link.get("rel")) == "next"
    ]
    if next_links:
        raise ValueError("USGS daily response exceeded one 10000-row page")
    if not features:
        raise ValueError("USGS daily API returned no discharge observations")

    flow_by_day: dict[date, float] = {}
    units_seen: set[str] = set()
    for feature in features:
        props = dict(feature.get("properties") or {})
        if str(props.get("monitoring_location_id")) != USGS_LOCATION_ID:
            raise ValueError("USGS monitoring location mismatch")
        if str(props.get("parameter_code")) != "00060" or str(props.get("statistic_id")) != "00003":
            raise ValueError("USGS daily parameter/statistic mismatch")
        day = date.fromisoformat(str(props.get("time"))[:10])
        if day < start or day > end:
            continue
        value_text = props.get("value")
        if value_text in (None, ""):
            continue
        try:
            discharge = float(value_text)
        except (TypeError, ValueError):
            continue
        unit = str(props.get("unit_of_measure") or "").strip().lower()
        units_seen.add(unit)
        if unit in {"ft3/s", "ft^3/s", "cfs", "ft³/s"}:
            discharge *= CFS_TO_M3S
        elif unit in {"m3/s", "m^3/s", "m³/s"}:
            pass
        else:
            raise ValueError(f"unsupported USGS discharge unit: {unit!r}")
        if discharge < 0:
            continue
        if day in flow_by_day and abs(flow_by_day[day] - discharge) > 1e-9:
            raise ValueError(f"conflicting USGS daily discharge values for {day}")
        flow_by_day[day] = discharge

    flow_rows = []
    for day, discharge in sorted(flow_by_day.items()):
        # Daily USGS values become usable in this replay model at the next UTC midnight.
        available_at = datetime.combine(day + timedelta(days=1), time.min, timezone.utc)
        flow_rows.append(
            FlowObservation(
                valid_date=day,
                discharge_m3s=discharge,
                source="usgs-waterdata-daily-00060-00003",
                available_at=available_at,
            )
        )
    if len(flow_rows) < 2:
        raise ValueError("insufficient USGS daily discharge for calibration")
    (output / "flow.jsonl").write_text(
        "\n".join(r.model_dump_json() for r in flow_rows) + "\n", encoding="utf-8"
    )
    (output / "basin.json").write_text(json.dumps(basin, sort_keys=True), encoding="utf-8")
    provenance = dict(
        source="Caravan MultiMet + USGS Water Data API",
        version="v1.1",
        product="ERA5_LAND",
        basin_index=basin_index,
        day_timezone="UTC",
        source_attributes=attrs,
        available_at_policy="retrieval_upper_bound for forcing; next-UTC-midnight for USGS daily flow",
        retrieved_at=retrieved.isoformat(),
        raw_files=receipts,
        area_source=(
            "Pinned current USGS monitoring-location metadata: USGS-13235000 drainage area "
            "446 square miles"
        ),
        observations=(
            "USGS Water Data OGC daily mean discharge, parameter 00060/statistic 00003, "
            "converted to m3/s"
        ),
        observation_units=sorted(units_seen),
        normalized_files={
            name: sha256_file(output / name)
            for name in ("forcing.jsonl", "flow.jsonl", "basin.json")
        },
    )
    (output / "source-manifest.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "source": str(output.resolve()),
                "rows": len(rows),
                "flow_rows": len(flow_rows),
                "area_km2": area_km2,
                "precipitation_range": [
                    min(r.precipitation_mm_day for r in rows),
                    max(r.precipitation_mm_day for r in rows),
                ],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2019, 5, 3))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2020, 5, 4))
    args = parser.parse_args()
    prepare(args.output, args.start, args.end)
