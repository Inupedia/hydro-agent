"""Download only official MultiMet chunks needed for Lowman, plus USGS metadata.

This ingestion command runs outside numerical workspaces. Raw bytes and hashes
are retained. No secret or LLM client is used.
"""

import argparse
import csv
import json
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
from numcodecs import get_codec

from hydro_agent.data.contracts import FlowObservation, ForcingRow
from hydro_agent.execution.hashing import sha256_file

BASE = "https://storage.googleapis.com/caravan-multimet/v1.1/ERA5_LAND/timeseries.zarr/"
SITE = "https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=13235000&siteOutput=expanded"
DV = "https://waterservices.usgs.gov/nwis/dv/?format=json&sites=13235000&parameterCd=00060&siteStatus=all"
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
                "60",
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
            )
        )
        return destination.read_bytes()

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
    site_text = download(SITE, "usgs-site.rdb").decode("utf-8")
    lines = [s for s in site_text.splitlines() if s and not s.startswith("#")]
    site = list(csv.DictReader([lines[0], *lines[2:]], delimiter="\t"))
    if len(site) != 1 or site[0]["site_no"] != "13235000":
        raise ValueError("USGS station mismatch")
    area_km2 = float(site[0]["drain_area_va"]) * 2.589988110336
    basin = dict(
        basin_id="camels_13235000",
        station_id="USGS-13235000",
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
    flow_url = f"{DV}&startDT={start.isoformat()}&endDT={end.isoformat()}"
    flow_bytes = download(flow_url, "usgs-dv-00060.json")
    flow_payload = json.loads(flow_bytes.decode("utf-8"))
    dv_values = flow_payload["value"]["timeSeries"][0]["values"][0]["value"]
    flow_rows = []
    for item in dv_values:
        day = date.fromisoformat(item["dateTime"][:10])
        if day < start or day > end:
            continue
        value_text = item.get("value")
        if value_text in (None, ""):
            continue
        try:
            discharge = float(value_text) * CFS_TO_M3S
        except ValueError:
            continue
        if discharge < 0:
            continue
        # Daily USGS values become available at the next UTC midnight.
        available_at = datetime.combine(day + timedelta(days=1), time.min, timezone.utc)
        flow_rows.append(
            FlowObservation(
                valid_date=day,
                discharge_m3s=discharge,
                source="usgs-nwis-dv-00060",
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
        source="Caravan MultiMet + USGS NWIS DV",
        version="v1.1",
        product="ERA5_LAND",
        basin_index=basin_index,
        day_timezone="UTC",
        source_attributes=attrs,
        available_at_policy="retrieval_upper_bound for forcing; next-UTC-midnight for USGS DV flow",
        retrieved_at=retrieved.isoformat(),
        raw_files=receipts,
        area_source="USGS drain_area_va, square miles * 2.589988110336",
        observations="usgs-nwis daily discharge 00060 (cfs->m3/s) for calibration/evaluation",
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
