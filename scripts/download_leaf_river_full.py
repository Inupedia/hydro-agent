#!/usr/bin/env python3
"""Download a source-proven Leaf River package for XAJ basin preparation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import time as time_module
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import numpy as np
import rasterio
from netCDF4 import Dataset, num2date
from pyproj import Geod
from rasterio.features import geometry_mask
from shapely import contains_xy
from shapely.geometry import shape

from hydro_agent.data.adapters.open_basin import CFS_TO_M3S

BASIN_ID = "usgs_02472000"
USGS_SITE = "02472000"
MODEL_START = date(1979, 1, 1)
MODEL_END = date(2025, 12, 31)
Q_START = date(1938, 9, 12)
USER_AGENT = "Hydro-Agent/0.1 (Leaf River research data package)"
NLDI_ROOT = f"https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-{USGS_SITE}"
GRIDMET_ROOT = "http://thredds.northwestknowledge.net:8080/thredds/ncss/grid"
GRIDMET = {
    "precipitation": ("agg_met_pr_1979_CurrentYear_CONUS.nc", "precipitation_amount"),
    "pet": (
        "agg_met_pet_1979_CurrentYear_CONUS.nc",
        "daily_mean_reference_evapotranspiration_grass",
    ),
    "temperature_max": (
        "agg_met_tmmx_1979_CurrentYear_CONUS.nc",
        "daily_maximum_temperature",
    ),
    "temperature_min": (
        "agg_met_tmmn_1979_CurrentYear_CONUS.nc",
        "daily_minimum_temperature",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def fetch(url: str, destination: Path, *, timeout: int = 300) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    error: Exception | None = None
    for attempt in range(5):
        try:
            with (
                urllib.request.urlopen(request, timeout=timeout) as response,
                part.open("wb") as out,
            ):
                shutil.copyfileobj(response, out)
            part.replace(destination)
            return {
                "url": url,
                "file": str(destination),
                "bytes": destination.stat().st_size,
                "sha256": sha256(destination),
            }
        except Exception as exc:  # noqa: BLE001 - bounded retry with final source error
            error = exc
            part.unlink(missing_ok=True)
            if attempt == 4:
                break
            time_module.sleep(2 * (attempt + 1))
    assert error is not None
    raise error


def parse_usgs_site(path: Path) -> dict[str, object]:
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    rows = list(csv.DictReader([lines[0], *lines[2:]], delimiter="\t"))
    if len(rows) != 1 or rows[0]["site_no"] != USGS_SITE:
        raise ValueError("USGS station metadata mismatch")
    row = rows[0]
    return {
        "basin_id": BASIN_ID,
        "station_id": f"USGS-{USGS_SITE}",
        "usgs_site": USGS_SITE,
        "name": row["station_nm"],
        "latitude": float(row["dec_lat_va"]),
        "longitude": float(row["dec_long_va"]),
        "area_km2": float(row["drain_area_va"]) * 2.589988110336,
        "day_timezone": "UTC",
        "source_timezone": row["tz_cd"],
        "adapter": "open-v2-spatial",
        "forcing": "gridmet-basin-grid",
        "terrain": "usgs-3dep-30m",
        "boundary": "usgs-nldi-unsimplified",
    }


def polygon_area_km2(geometry: dict) -> float:
    area_m2, _ = Geod(ellps="WGS84").geometry_area_perimeter(shape(geometry))
    return abs(area_m2) / 1_000_000


def download_gis(
    root: Path, site: dict[str, object]
) -> tuple[dict, tuple[float, float, float, float], list[dict]]:
    receipts = []
    urls = {
        "raw/nldi_feature.json": f"{NLDI_ROOT}?f=json",
        "boundary.geojson": f"{NLDI_ROOT}/basin?f=json&simplified=false",
        "boundary_simplified.geojson": f"{NLDI_ROOT}/basin?f=json&simplified=true",
        "flowlines.geojson": f"{NLDI_ROOT}/navigation/UT/flowlines?f=json&distance=160",
    }
    for relative, url in urls.items():
        print(f"GIS {relative}", flush=True)
        receipts.append(fetch(url, root / "gis" / relative))
    boundary_fc = json.loads((root / "gis" / "boundary.geojson").read_text(encoding="utf-8"))
    if len(boundary_fc.get("features", [])) != 1:
        raise ValueError("NLDI basin must contain exactly one feature")
    geometry = boundary_fc["features"][0]["geometry"]
    basin_shape = shape(geometry)
    bbox = basin_shape.bounds
    nldi_area = polygon_area_km2(geometry)
    usgs_area = float(site["area_km2"])
    area_ratio = min(usgs_area, nldi_area) / max(usgs_area, nldi_area)
    if area_ratio < 0.9:
        raise ValueError(f"NLDI/USGS drainage area mismatch: {area_ratio:.3f}")
    write_json(
        root / "gis" / "outlet.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"usgs_site": USGS_SITE, "name": site["name"]},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [site["longitude"], site["latitude"]],
                    },
                }
            ],
        },
    )
    west, south, east, north = bbox
    write_json(
        root / "gis" / "bbox.json",
        {"west": west, "south": south, "east": east, "north": north},
    )
    write_json(
        root / "gis" / "boundary_check.json",
        {
            "accepted": True,
            "usgs_area_km2": usgs_area,
            "nldi_area_km2_geodesic": nldi_area,
            "area_ratio": area_ratio,
            "outlet": [site["longitude"], site["latitude"]],
            "boundary_source": "USGS NLDI unsimplified basin",
        },
    )
    return geometry, bbox, receipts


def gridmet_url(
    dataset: str,
    variable: str,
    bbox: tuple[float, float, float, float],
    start: date,
    end: date,
) -> str:
    west, south, east, north = bbox
    params = urllib.parse.urlencode(
        {
            "var": variable,
            "north": f"{north:.6f}",
            "west": f"{west:.6f}",
            "east": f"{east:.6f}",
            "south": f"{south:.6f}",
            "horizStride": "1",
            "time_start": f"{start.isoformat()}T00:00:00Z",
            "time_end": f"{end.isoformat()}T00:00:00Z",
            "timeStride": "1",
            "accept": "netcdf",
        }
    )
    return f"{GRIDMET_ROOT}/{dataset}?{params}"


def decade_ranges(start: date, end: date):
    current = start
    while current <= end:
        chunk_end = min(date(current.year + 9, 12, 31), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def download_gridmet(
    root: Path, bbox: tuple[float, float, float, float]
) -> tuple[dict[str, list[Path]], list[dict]]:
    pad = 0.08
    west, south, east, north = bbox
    download_bbox = (west - pad, south - pad, east + pad, north + pad)
    files: dict[str, list[Path]] = {name: [] for name in GRIDMET}
    receipts = []
    for name, (dataset, variable) in GRIDMET.items():
        for start, end in decade_ranges(MODEL_START, MODEL_END):
            target = root / "hydro" / "gridded" / f"gridmet_{name}_{start.year}_{end.year}.nc"
            print(f"GridMET {name} {start}..{end}", flush=True)
            url = gridmet_url(dataset, variable, download_bbox, start, end)
            if target.is_file():
                with Dataset(target) as cached:
                    if variable not in cached.variables:
                        raise ValueError(f"cached GridMET variable mismatch: {target}")
                receipt = {
                    "url": url,
                    "file": str(target),
                    "bytes": target.stat().st_size,
                    "sha256": sha256(target),
                    "reused": True,
                }
            else:
                receipt = fetch(url, target)
            receipt.update(variable=variable, start=start.isoformat(), end=end.isoformat())
            receipts.append(receipt)
            files[name].append(target)
    return files, receipts


def read_gridmet(
    files: list[Path], variable: str
) -> tuple[np.ndarray, np.ndarray, dict[date, np.ndarray], str]:
    all_values: dict[date, np.ndarray] = {}
    expected_lat = expected_lon = None
    units = ""
    for path in files:
        with Dataset(path) as dataset:
            lat = np.asarray(dataset.variables["lat"][:], dtype=float)
            lon = np.asarray(dataset.variables["lon"][:], dtype=float)
            if expected_lat is None:
                expected_lat, expected_lon = lat, lon
            elif not np.array_equal(expected_lat, lat) or not np.array_equal(expected_lon, lon):
                raise ValueError(f"GridMET grid drift in {path}")
            time_var = dataset.variables["day"]
            dates = num2date(time_var[:], time_var.units, only_use_cftime_datetimes=False)
            values = dataset.variables[variable][:]
            units = str(getattr(dataset.variables[variable], "units", ""))
            for dt, array in zip(dates, values, strict=True):
                day = date(int(dt.year), int(dt.month), int(dt.day))
                if day in all_values:
                    raise ValueError(f"duplicate GridMET date {day} for {variable}")
                all_values[day] = np.ma.asarray(array)
    assert expected_lat is not None and expected_lon is not None
    return expected_lat, expected_lon, all_values, units


def download_usgs_flow(root: Path, retrieved_at: datetime) -> tuple[list[dict], list[dict]]:
    receipts = []
    records: dict[date, dict] = {}
    for start, end in decade_ranges(Q_START, retrieved_at.date()):
        url = (
            "https://api.waterdata.usgs.gov/ogcapi/v0/collections/daily/items?"
            + urllib.parse.urlencode(
                {
                    "f": "json",
                    "limit": "10000",
                    "datetime": f"{start.isoformat()}/{end.isoformat()}",
                    "monitoring_location_id": f"USGS-{USGS_SITE}",
                    "parameter_code": "00060",
                    "statistic_id": "00003",
                }
            )
        )
        target = root / "hydro" / "raw" / f"usgs_daily_{start.year}_{end.year}.json"
        print(f"USGS Q {start}..{end}", flush=True)
        if target.is_file():
            receipt = {
                "url": url,
                "file": str(target),
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
                "reused": True,
            }
        else:
            receipt = fetch(url, target)
        receipt.update(start=start.isoformat(), end=end.isoformat())
        receipts.append(receipt)
        payload = json.loads(target.read_text(encoding="utf-8"))
        for feature in payload.get("features", []):
            item = feature["properties"]
            if item["monitoring_location_id"] != f"USGS-{USGS_SITE}":
                raise ValueError("USGS flow station mismatch")
            if item["unit_of_measure"] != "ft^3/s":
                raise ValueError("unexpected USGS discharge unit")
            day = date.fromisoformat(item["time"][:10])
            value = float(item["value"])
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid discharge on {day}: {value}")
            records[day] = item
    ordered = [records[day] for day in sorted(records)]
    if not ordered:
        raise ValueError("USGS returned no daily discharge")
    return ordered, receipts


def download_dem(root: Path, bbox: tuple[float, float, float, float], geometry: dict) -> dict:
    pad = 0.05
    west, south, east, north = bbox
    west, south, east, north = west - pad, south - pad, east + pad, north + pad
    latitude = (south + north) / 2
    width = math.ceil((east - west) * 111_320 * math.cos(math.radians(latitude)) / 30)
    height = math.ceil((north - south) * 111_320 / 30)
    if width > 4000 or height > 4000:
        raise ValueError(f"3DEP export too large: {width}x{height}")
    params = urllib.parse.urlencode(
        {
            "bbox": f"{west},{south},{east},{north}",
            "bboxSR": "4326",
            "size": f"{width},{height}",
            "imageSR": "4326",
            "format": "tiff",
            "pixelType": "F32",
            "interpolation": "RSP_BilinearInterpolation",
            "f": "image",
        }
    )
    url = (
        "https://elevation.nationalmap.gov/arcgis/rest/services/"
        f"3DEPElevation/ImageServer/exportImage?{params}"
    )
    target = root / "dem" / "leaf_river_3dep_30m.tif"
    print(f"USGS 3DEP DEM {width}x{height}", flush=True)
    if target.is_file():
        receipt = {
            "url": url,
            "file": str(target),
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
            "reused": True,
        }
    else:
        receipt = fetch(url, target, timeout=600)
    receipt["file"] = str(target.relative_to(root))
    with rasterio.open(target) as dataset:
        if dataset.crs is None or dataset.crs.to_epsg() != 4326:
            raise ValueError(f"unexpected DEM CRS {dataset.crs}")
        elevation = dataset.read(1, masked=True)
        inside = geometry_mask([geometry], dataset.shape, dataset.transform, invert=True)
        valid_inside = (
            inside & ~np.ma.getmaskarray(elevation) & np.isfinite(elevation.filled(np.nan))
        )
        coverage = int(valid_inside.sum()) / int(inside.sum())
        if coverage < 0.999:
            raise ValueError(f"DEM basin coverage too low: {coverage:.6f}")
        values = np.asarray(elevation)[valid_inside]
        profile = {
            "width": dataset.width,
            "height": dataset.height,
            "crs": str(dataset.crs),
            "bounds": list(dataset.bounds),
            "resolution_degrees": list(dataset.res),
            "basin_valid_fraction": coverage,
            "basin_elevation_min_m": float(values.min()),
            "basin_elevation_max_m": float(values.max()),
            "basin_elevation_mean_m": float(values.mean()),
        }
    manifest = {
        "provider": "USGS 3D Elevation Program seamless elevation service",
        "product": "3DEP approximately 30 m export",
        "downloaded": receipt,
        **profile,
    }
    write_json(root / "dem" / "sources.json", manifest)
    return manifest


def materialize_hydro(
    root: Path,
    site: dict[str, object],
    geometry: dict,
    grid_files: dict[str, list[Path]],
    usgs_records: list[dict],
    retrieved_at: datetime,
) -> dict[str, object]:
    decoded = {}
    grids = {}
    source_units = {}
    for name, (_, variable) in GRIDMET.items():
        lat, lon, values, units = read_gridmet(grid_files[name], variable)
        decoded[name] = values
        grids[name] = (lat, lon)
        source_units[name] = units
    base_lat, base_lon = grids["precipitation"]
    for name, (lat, lon) in grids.items():
        if not np.array_equal(base_lat, lat) or not np.array_equal(base_lon, lon):
            raise ValueError(f"GridMET coordinate mismatch for {name}")
    xs, ys = np.meshgrid(base_lon, base_lat)
    cell_mask = contains_xy(shape(geometry), xs, ys)
    if int(cell_mask.sum()) < 4:
        raise ValueError("too few GridMET cells inside basin")
    expected_days = [
        MODEL_START + timedelta(days=i) for i in range((MODEL_END - MODEL_START).days + 1)
    ]
    for name, values in decoded.items():
        missing = [day for day in expected_days if day not in values]
        if missing:
            raise ValueError(f"GridMET {name} missing {len(missing)} days; first={missing[:3]}")
    q_by_day = {date.fromisoformat(item["time"][:10]): item for item in usgs_records}
    missing_q = [day for day in expected_days if day not in q_by_day]
    if len(missing_q) > 5:
        raise ValueError(
            f"USGS discharge missing {len(missing_q)} model days; first={missing_q[:10]}"
        )
    imputations = []
    for day in missing_q:
        previous = q_by_day.get(day - timedelta(days=1))
        following = q_by_day.get(day + timedelta(days=1))
        if previous is None or following is None:
            raise ValueError(f"cannot interpolate isolated USGS gap on {day}")
        interpolated = (float(previous["value"]) + float(following["value"])) / 2
        q_by_day[day] = {
            "time": day.isoformat(),
            "value": str(interpolated),
            "approval_status": "IMPUTED",
            "qualifier": "LINEAR_INTERPOLATION",
            "last_modified": retrieved_at.isoformat(),
        }
        imputations.append(
            {
                "valid_date": day.isoformat(),
                "method": "linear interpolation between adjacent approved USGS daily values",
                "previous_date": (day - timedelta(days=1)).isoformat(),
                "previous_cfs": float(previous["value"]),
                "next_date": (day + timedelta(days=1)).isoformat(),
                "next_cfs": float(following["value"]),
                "imputed_cfs": interpolated,
                "risk": "exclude or mask this date in formal scoring sensitivity checks",
            }
        )

    forcing_lines = []
    supplemental_lines = []
    flow_lines = []
    precipitation_values = []
    pet_values = []
    discharge_values = []
    for day in expected_days:
        precipitation = float(np.ma.mean(decoded["precipitation"][day][cell_mask]))
        pet = float(np.ma.mean(decoded["pet"][day][cell_mask]))
        tmax = float(np.ma.mean(decoded["temperature_max"][day][cell_mask]))
        tmin = float(np.ma.mean(decoded["temperature_min"][day][cell_mask]))
        if source_units["temperature_max"].lower().startswith("k"):
            tmax -= 273.15
            tmin -= 273.15
        if min(precipitation, pet) < 0 or not all(
            map(math.isfinite, (precipitation, pet, tmin, tmax))
        ):
            raise ValueError(f"invalid forcing on {day}")
        if tmin > tmax:
            raise ValueError(f"Tmin exceeds Tmax on {day}")
        forcing_lines.append(
            json.dumps(
                {
                    "valid_date": day.isoformat(),
                    "precipitation_mm_day": precipitation,
                    "pet_mm_day": pet,
                    "source_kind": "reanalysis",
                    "source": "gridmet-spatial-basin-mean",
                    "available_at": retrieved_at.isoformat(),
                },
                allow_nan=False,
            )
        )
        supplemental_lines.append(
            json.dumps(
                {
                    "valid_date": day.isoformat(),
                    "temperature_min_c": tmin,
                    "temperature_max_c": tmax,
                },
                allow_nan=False,
            )
        )
        q = q_by_day[day]
        available_at = (
            q.get("last_modified")
            or datetime.combine(day + timedelta(days=1), time.min, timezone.utc).isoformat()
        )
        discharge = float(q["value"]) * CFS_TO_M3S
        flow_source = (
            "linear-interpolation-of-usgs-daily-00060"
            if q.get("approval_status") == "IMPUTED"
            else "usgs-waterdata-ogc-daily-00060-00003"
        )
        flow_lines.append(
            json.dumps(
                {
                    "valid_date": day.isoformat(),
                    "discharge_m3s": discharge,
                    "source": flow_source,
                    "available_at": available_at,
                },
                allow_nan=False,
            )
        )
        precipitation_values.append(precipitation)
        pet_values.append(pet)
        discharge_values.append(discharge)
    hydro = root / "hydro"
    (hydro / "forcing.jsonl").write_text("\n".join(forcing_lines) + "\n", encoding="utf-8")
    (hydro / "forcing_supplemental.jsonl").write_text(
        "\n".join(supplemental_lines) + "\n", encoding="utf-8"
    )
    (hydro / "flow.jsonl").write_text("\n".join(flow_lines) + "\n", encoding="utf-8")

    all_flow = []
    flags = []
    for item in usgs_records:
        day = date.fromisoformat(item["time"][:10])
        available_at = (
            item.get("last_modified")
            or datetime.combine(day + timedelta(days=1), time.min, timezone.utc).isoformat()
        )
        all_flow.append(
            json.dumps(
                {
                    "valid_date": day.isoformat(),
                    "discharge_m3s": float(item["value"]) * CFS_TO_M3S,
                    "source": "usgs-waterdata-ogc-daily-00060-00003",
                    "available_at": available_at,
                },
                allow_nan=False,
            )
        )
        flags.append(
            json.dumps(
                {
                    "valid_date": day.isoformat(),
                    "approval_status": item.get("approval_status"),
                    "qualifier": item.get("qualifier"),
                    "last_modified": item.get("last_modified"),
                }
            )
        )
    (hydro / "flow_all.jsonl").write_text("\n".join(all_flow) + "\n", encoding="utf-8")
    (hydro / "flow_quality_flags.jsonl").write_text("\n".join(flags) + "\n", encoding="utf-8")
    (hydro / "flow_imputations.jsonl").write_text(
        "\n".join(json.dumps(item) for item in imputations) + ("\n" if imputations else ""),
        encoding="utf-8",
    )
    write_json(hydro / "basin.json", site)
    write_json(
        hydro / "outlet.json",
        {
            "latitude": site["latitude"],
            "longitude": site["longitude"],
            "area_km2": site["area_km2"],
            "usgs_site": USGS_SITE,
        },
    )
    grid_cells = [
        {
            "row": int(row),
            "column": int(column),
            "latitude": float(base_lat[row]),
            "longitude": float(base_lon[column]),
        }
        for row, column in np.argwhere(cell_mask)
    ]
    write_json(
        hydro / "forcing_grid_index.json",
        {
            "cell_center_rule": "Grid cell center is covered by NLDI basin polygon",
            "selected_cell_count": len(grid_cells),
            "cells": grid_cells,
        },
    )
    qualifiers = {}
    approvals = {}
    for item in usgs_records:
        raw_qualifier = item.get("qualifier")
        qualifier = (
            ",".join(sorted(str(value) for value in raw_qualifier))
            if isinstance(raw_qualifier, list)
            else str(raw_qualifier or "NONE")
        )
        qualifiers[qualifier] = qualifiers.get(qualifier, 0) + 1
        approval = item.get("approval_status") or "UNKNOWN"
        approvals[approval] = approvals.get(approval, 0) + 1
    return {
        "model_start": MODEL_START.isoformat(),
        "model_end": MODEL_END.isoformat(),
        "model_days": len(expected_days),
        "forcing_days": len(forcing_lines),
        "flow_days": len(flow_lines),
        "observed_model_flow_days": len(flow_lines) - len(imputations),
        "imputed_model_flow_days": len(imputations),
        "imputed_model_flow_dates": [item["valid_date"] for item in imputations],
        "full_flow_start": usgs_records[0]["time"][:10],
        "full_flow_end": usgs_records[-1]["time"][:10],
        "full_flow_days": len(usgs_records),
        "selected_grid_cells": int(cell_mask.sum()),
        "approval_status_counts": approvals,
        "qualifier_counts": qualifiers,
        "precipitation_min_mm_day": min(precipitation_values),
        "precipitation_max_mm_day": max(precipitation_values),
        "pet_min_mm_day": min(pet_values),
        "pet_max_mm_day": max(pet_values),
        "discharge_min_m3s": min(discharge_values),
        "discharge_max_m3s": max(discharge_values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/basins") / BASIN_ID)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing directory: {output}")
    staging = output.parent / f".{output.name}.staging"
    staging.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc)
    try:
        site_url = (
            "https://waterservices.usgs.gov/nwis/site/"
            f"?format=rdb&sites={USGS_SITE}&siteOutput=expanded"
        )
        site_receipt = fetch(site_url, staging / "hydro" / "raw" / "usgs_site.rdb")
        site = parse_usgs_site(staging / "hydro" / "raw" / "usgs_site.rdb")
        geometry, bbox, gis_receipts = download_gis(staging, site)
        grid_files, grid_receipts = download_gridmet(staging, bbox)
        usgs_records, flow_receipts = download_usgs_flow(staging, retrieved_at)
        dem_manifest = download_dem(staging, bbox, geometry)
        profile = materialize_hydro(staging, site, geometry, grid_files, usgs_records, retrieved_at)
        raw_receipts = [site_receipt, *gis_receipts, *grid_receipts, *flow_receipts]
        for receipt in raw_receipts:
            receipt["file"] = str(Path(str(receipt["file"])).relative_to(staging))
        write_json(
            staging / "hydro" / "source-manifest.json",
            {
                "dataset": "USGS 02472000 Leaf River near Collins complete XAJ package",
                "adapter": "open-v2-spatial",
                "retrieved_at": retrieved_at.isoformat(),
                "time_semantics": {
                    "normalized_day_timezone": "UTC",
                    "usgs_source_timezone": site["source_timezone"],
                    "forcing_mode": "R",
                    "note": (
                        "GridMET is retrospective; historical operational availability "
                        "is not asserted."
                    ),
                },
                "profile": profile,
                "dem": dem_manifest,
                "raw_receipts": raw_receipts,
            },
        )
        write_json(
            staging / "catalog.json",
            {
                "basin_id": BASIN_ID,
                "usgs_site": USGS_SITE,
                "label": "Leaf River near Collins (MS)",
                "region": "Mississippi, USA",
                "kind": "downloaded",
                "adapter": "open-v2-spatial",
                "default_start": MODEL_START.isoformat(),
                "default_end": MODEL_END.isoformat(),
                "primary": False,
                "status": "complete",
                "missing": [],
                "materials": {"hydro": True, "dem": True, "gis": True},
                "ready_for_build": True,
                "complete": True,
            },
        )
        write_json(
            staging / "README.json",
            {
                "purpose": "Source-proven Leaf River data for XAJ basin/unit preparation",
                "model_ready_common_period": [MODEL_START.isoformat(), MODEL_END.isoformat()],
                "directories": {
                    "hydro": (
                        "Normalized P/PET/Q, supplemental temperature, raw GridMET "
                        "and USGS receipts"
                    ),
                    "gis": "NLDI full/simplified boundary, outlet and upstream flowlines",
                    "dem": "USGS 3DEP GeoTIFF and source/coverage manifest",
                },
                "distributed_forcing_note": (
                    "Aggregate hydro/gridded NetCDF P/PET by DEM-derived unit; "
                    "do not duplicate the basin mean across units."
                ),
            },
        )
        staging.replace(output)
        print(json.dumps({"output": str(output), **profile}, indent=2), flush=True)
    except Exception:
        print(f"Partial download retained for diagnosis: {staging}", flush=True)
        raise


if __name__ == "__main__":
    main()
