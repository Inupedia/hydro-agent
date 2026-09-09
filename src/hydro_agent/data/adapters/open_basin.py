"""Open-data hydro adapters: USGS gauge → NLDI → gridMET → BasinCase."""

from __future__ import annotations

import csv
import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from hydro_agent.data.contracts import FlowObservation, ForcingRow
from hydro_agent.execution.hashing import sha256_file
from hydro_agent.modeling.plans import write_json

CFS_TO_M3S = 0.028316846592
USER_AGENT = "Hydro-Agent/0.1 (open-data-adapter; research)"
GRIDMET_PR = "http://thredds.northwestknowledge.net:8080/thredds/ncss/grid/agg_met_pr_1979_CurrentYear_CONUS.nc"
GRIDMET_PET = "http://thredds.northwestknowledge.net:8080/thredds/ncss/grid/agg_met_pet_1979_CurrentYear_CONUS.nc"
# NCSS CSV/netCDF subsets often omit scale_factor; gridMET packs with 0.1.
GRIDMET_SCALE = 0.1


@dataclass(frozen=True)
class GaugeSpec:
    usgs_site: str
    basin_id: str
    label: str
    region: str = "USA"


LEAF_RIVER = GaugeSpec(
    usgs_site="02472000",
    basin_id="usgs_02472000",
    label="Leaf River near Collins (MS)",
    region="Mississippi, USA",
)


ProgressCb = Callable[[str, str, float], None]


def _http_get(url: str, destination: Path | None = None, timeout: int = 180) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    return payload


def fetch_usgs_site(usgs_site: str) -> dict[str, Any]:
    url = (
        "https://waterservices.usgs.gov/nwis/site/"
        f"?format=rdb&sites={usgs_site}&siteOutput=expanded"
    )
    text = _http_get(url).decode("utf-8")
    lines = [s for s in text.splitlines() if s and not s.startswith("#")]
    rows = list(csv.DictReader([lines[0], *lines[2:]], delimiter="\t"))
    if len(rows) != 1 or rows[0]["site_no"] != usgs_site:
        raise ValueError(f"USGS site mismatch for {usgs_site}")
    site = rows[0]
    return dict(
        usgs_site=usgs_site,
        station_id=f"USGS-{usgs_site}",
        name=site["station_nm"],
        latitude=float(site["dec_lat_va"]),
        longitude=float(site["dec_long_va"]),
        area_km2=float(site["drain_area_va"]) * 2.589988110336,
        day_timezone="UTC",
    )


def fetch_nldi_feature(usgs_site: str) -> dict[str, Any]:
    url = f"https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-{usgs_site}?f=json"
    return json.loads(_http_get(url).decode("utf-8"))


def fetch_nldi_basin(usgs_site: str, *, simplified: bool = True) -> dict[str, Any]:
    q = "simplified=true" if simplified else "simplified=false"
    url = f"https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-{usgs_site}/basin?f=json&{q}"
    return json.loads(_http_get(url).decode("utf-8"))


def polygon_bbox(geojson: dict[str, Any]) -> tuple[float, float, float, float]:
    feature = geojson["features"][0]
    geom = feature["geometry"]
    coords = geom["coordinates"]
    if geom["type"] == "Polygon":
        ring = coords[0]
    elif geom["type"] == "MultiPolygon":
        ring = coords[0][0]
    else:
        raise ValueError(f"unsupported geometry {geom['type']}")
    xs = [c[0] for c in ring]
    ys = [c[1] for c in ring]
    return min(xs), min(ys), max(xs), max(ys)


def polygon_area_km2_approx(geojson: dict[str, Any], latitude: float) -> float:
    """Planar approximation on local degrees→km; good enough for IoU area check."""
    feature = geojson["features"][0]
    geom = feature["geometry"]
    coords = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]
    # Shoelace in lon/lat then scale.
    area = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        area += x1 * y2 - x2 * y1
    area = abs(area) / 2.0
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * max(math.cos(math.radians(latitude)), 0.2)
    return area * km_per_deg_lat * km_per_deg_lon


def fetch_usgs_daily_discharge(
    usgs_site: str, start: date, end: date
) -> list[FlowObservation]:
    url = (
        "https://waterservices.usgs.gov/nwis/dv/?format=json"
        f"&sites={usgs_site}&parameterCd=00060&siteStatus=all"
        f"&startDT={start.isoformat()}&endDT={end.isoformat()}"
    )
    payload = json.loads(_http_get(url).decode("utf-8"))
    series = payload["value"]["timeSeries"]
    if not series:
        raise ValueError("USGS DV returned no time series")
    values = series[0]["values"][0]["value"]
    rows: list[FlowObservation] = []
    for item in values:
        day = date.fromisoformat(item["dateTime"][:10])
        if day < start or day > end:
            continue
        text = item.get("value")
        if text in (None, ""):
            continue
        try:
            discharge = float(text) * CFS_TO_M3S
        except ValueError:
            continue
        if discharge < 0:
            continue
        available_at = datetime.combine(day + timedelta(days=1), time.min, timezone.utc)
        rows.append(
            FlowObservation(
                valid_date=day,
                discharge_m3s=discharge,
                source="usgs-nwis-dv-00060",
                available_at=available_at,
            )
        )
    if len(rows) < 2:
        raise ValueError("insufficient USGS daily discharge")
    return rows


def _gridmet_csv(
    dataset_url: str,
    variable: str,
    *,
    latitude: float,
    longitude: float,
    start: date,
    end: date,
) -> list[tuple[date, float]]:
    params = urllib.parse.urlencode(
        {
            "var": variable,
            "latitude": f"{latitude:.6f}",
            "longitude": f"{longitude:.6f}",
            "time_start": f"{start.isoformat()}T00:00:00Z",
            "time_end": f"{end.isoformat()}T00:00:00Z",
            "accept": "csv",
        }
    )
    text = _http_get(f"{dataset_url}?{params}").decode("utf-8")
    reader = csv.DictReader(text.splitlines())
    field = next(k for k in (reader.fieldnames or []) if k not in ("time",) and "lat" not in k and "lon" not in k)
    out: list[tuple[date, float]] = []
    for row in reader:
        day = date.fromisoformat(row["time"][:10])
        raw = float(row[field])
        # NCSS often returns packed shorts without applying scale_factor.
        value = raw * GRIDMET_SCALE
        out.append((day, value))
    return out


def fetch_gridmet_forcing(
    *,
    latitude: float,
    longitude: float,
    start: date,
    end: date,
) -> list[ForcingRow]:
    precip = dict(
        _gridmet_csv(
            GRIDMET_PR,
            "precipitation_amount",
            latitude=latitude,
            longitude=longitude,
            start=start,
            end=end,
        )
    )
    pet = dict(
        _gridmet_csv(
            GRIDMET_PET,
            "daily_mean_reference_evapotranspiration_grass",
            latitude=latitude,
            longitude=longitude,
            start=start,
            end=end,
        )
    )
    days = sorted(set(precip) & set(pet))
    if len(days) < 2:
        raise ValueError("gridMET returned insufficient overlapping days")
    retrieved = datetime.now(timezone.utc)
    rows: list[ForcingRow] = []
    for day in days:
        rows.append(
            ForcingRow(
                valid_date=day,
                precipitation_mm_day=float(precip[day]),
                pet_mm_day=float(pet[day]),
                source_kind="reanalysis",
                source="gridmet-ncss-pr-pet-scaled-0.1",
                available_at=retrieved,
            )
        )
    return rows


def download_skadi_dem_for_bbox(
    dem_dir: Path,
    bbox: tuple[float, float, float, float],
    *,
    on_tile: ProgressCb | None = None,
) -> dict[str, Any]:
    import gzip
    import shutil

    west, south, east, north = bbox
    pad = 0.05
    west, south, east, north = west - pad, south - pad, east + pad, north + pad
    jobs = [
        (lat, lon)
        for lat in range(math.floor(south), math.ceil(north))
        for lon in range(math.floor(west), math.ceil(east))
    ]
    dem_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for index, (lat, lon) in enumerate(jobs):
        tile = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
        url = f"https://s3.amazonaws.com/elevation-tiles-prod/skadi/{tile[:3]}/{tile}.hgt.gz"
        packed = dem_dir / f"{tile}.hgt.gz"
        frac = (index + 1) / max(len(jobs), 1)
        if on_tile:
            on_tile("dem_tiles", packed.name, frac)
        if not packed.is_file():
            _http_get(url, packed)
        with gzip.open(packed, "rb") as stream:
            payload = stream.read()
        size = math.isqrt(len(payload) // 2)
        if size not in (1201, 3601) or len(payload) != size * size * 2:
            raise ValueError(f"Invalid HGT: {packed}")
        hgt = dem_dir / f"{tile}.hgt"
        hgt.write_bytes(payload)
        records.append(
            dict(
                file=packed.name,
                url=url,
                sha256=sha256_file(packed),
                samples_per_side=size,
                latitude=lat,
                longitude=lon,
            )
        )
    manifest = dict(
        provider="Mapzen/Tilezen Skadi (SRTM-based public tiles)",
        note="V1 terrain tiles for pyflwdir; professor stack prefers USGS 3DEP as next upgrade",
        download_bbox_wgs84=[west, south, east, north],
        tiles=records,
    )
    write_json(dem_dir / "sources.json", manifest)
    return manifest


def build_open_basin_case(
    root: Path,
    spec: GaugeSpec,
    *,
    start: date,
    end: date,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Full open-data path: gauge → NLDI → gridMET → USGS Q → DEM tiles → hydro/gis/dem."""

    def report(stage: str, current: str, frac: float) -> None:
        if progress:
            progress(stage, current, frac)

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    report("gauge", "usgs-site", 0.05)
    site = fetch_usgs_site(spec.usgs_site)
    report("nldi", "feature", 0.12)
    feature = fetch_nldi_feature(spec.usgs_site)
    report("nldi", "basin", 0.2)
    basin_gj = fetch_nldi_basin(spec.usgs_site, simplified=True)
    bbox = polygon_bbox(basin_gj)
    nldi_area = polygon_area_km2_approx(basin_gj, site["latitude"])
    iou_proxy = min(site["area_km2"], nldi_area) / max(site["area_km2"], nldi_area)

    gis = root / "gis"
    gis.mkdir(parents=True, exist_ok=True)
    write_json(gis / "boundary.geojson", basin_gj)
    write_json(gis / "nldi_feature.json", feature)
    write_json(
        gis / "outlet.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"usgs_site": spec.usgs_site, "name": site["name"]},
                    "geometry": {
                        "type": "Point",
                        "coordinates": [site["longitude"], site["latitude"]],
                    },
                }
            ],
        },
    )
    write_json(gis / "bbox.json", dict(west=bbox[0], south=bbox[1], east=bbox[2], north=bbox[3]))
    boundary_check = dict(
        accepted=iou_proxy >= 0.7,
        usgs_area_km2=site["area_km2"],
        nldi_area_km2_approx=nldi_area,
        area_ratio=iou_proxy,
        snap_note="NLDI basin polygon vs USGS drain_area_va",
        outlet=[site["longitude"], site["latitude"]],
    )
    write_json(gis / "boundary_check.json", boundary_check)
    if not boundary_check["accepted"]:
        raise ValueError(f"NLDI/USGS area ratio too low: {iou_proxy:.3f}")

    report("gridmet", "precipitation+pet", 0.45)
    forcing = fetch_gridmet_forcing(
        latitude=site["latitude"], longitude=site["longitude"], start=start, end=end
    )
    report("usgs_flow", "daily-values", 0.65)
    flow = fetch_usgs_daily_discharge(spec.usgs_site, start, end)
    # Align dates
    force_days = {r.valid_date for r in forcing}
    flow_days = {r.valid_date for r in flow}
    common = sorted(force_days & flow_days)
    if len(common) < 14:
        raise ValueError(f"aligned days too few: {len(common)}")
    forcing = [r for r in forcing if r.valid_date in set(common)]
    flow = [r for r in flow if r.valid_date in set(common)]

    hydro = root / "hydro"
    hydro.mkdir(parents=True, exist_ok=True)
    (hydro / "forcing.jsonl").write_text(
        "\n".join(r.model_dump_json() for r in forcing) + "\n", encoding="utf-8"
    )
    (hydro / "flow.jsonl").write_text(
        "\n".join(r.model_dump_json() for r in flow) + "\n", encoding="utf-8"
    )
    basin = dict(
        basin_id=spec.basin_id,
        station_id=site["station_id"],
        usgs_site=spec.usgs_site,
        area_km2=site["area_km2"],
        latitude=site["latitude"],
        longitude=site["longitude"],
        day_timezone="UTC",
        name=site["name"],
        adapter="open-v1",
        forcing="gridmet",
        terrain="skadi-v1",
        boundary="nldi",
    )
    write_json(hydro / "basin.json", basin)
    write_json(
        hydro / "outlet.json",
        dict(
            latitude=site["latitude"],
            longitude=site["longitude"],
            area_km2=site["area_km2"],
            usgs_site=spec.usgs_site,
        ),
    )
    write_json(
        hydro / "source-manifest.json",
        dict(
            adapter="open-v1",
            gauge=spec.usgs_site,
            start=start.isoformat(),
            end=end.isoformat(),
            n_forcing=len(forcing),
            n_flow=len(flow),
            boundary_check=boundary_check,
            gridmet_scale_factor=GRIDMET_SCALE,
            sources=[
                "USGS NWIS site + DV",
                "USGS NLDI basin",
                "gridMET NCSS pr+pet",
                "Skadi DEM tiles (3DEP upgrade path)",
            ],
        ),
    )

    def dem_progress(stage: str, name: str, frac: float) -> None:
        report(stage, name, 0.75 + 0.2 * frac)

    dem_manifest = download_skadi_dem_for_bbox(root / "dem", bbox, on_tile=dem_progress)
    report("done", "complete", 1.0)
    return dict(
        basin_id=spec.basin_id,
        usgs_site=spec.usgs_site,
        boundary_check=boundary_check,
        n_forcing=len(forcing),
        n_flow=len(flow),
        dem_tiles=len(dem_manifest["tiles"]),
        data_start=common[0].isoformat(),
        data_end=common[-1].isoformat(),
        precip_mean=sum(r.precipitation_mm_day for r in forcing) / len(forcing),
        pet_mean=sum(r.pet_mm_day for r in forcing) / len(forcing),
        q_mean=sum(r.discharge_m3s for r in flow) / len(flow),
    )
