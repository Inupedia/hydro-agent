"""Async basin material downloads with pollable progress."""

from __future__ import annotations

import csv
import gzip
import json
import math
import shutil
import threading
import uuid
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
from numcodecs import get_codec

from hydro_agent.data.contracts import FlowObservation, ForcingRow
from hydro_agent.execution.hashing import sha256_file
from hydro_agent.modeling.basins import BasinCatalog
from hydro_agent.modeling.plans import write_json

MULTIMET_BASE = "https://storage.googleapis.com/caravan-multimet/v1.1/ERA5_LAND/timeseries.zarr/"
CFS_TO_M3S = 0.028316846592


class BasinDownloadService:
    def __init__(self, catalog: BasinCatalog):
        self.catalog = catalog
        self.root = catalog.root / "_download-jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.RLock()

    def _job_path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_path(job_id)
        if not path.is_file():
            raise KeyError(job_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list_jobs(self, basin_id: str | None = None) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(self.root.glob("*.json"), reverse=True):
            row = json.loads(path.read_text(encoding="utf-8"))
            if basin_id and row.get("basin_id") != basin_id:
                continue
            rows.append(row)
        return rows

    def _update(self, job_id: str, **fields: Any) -> dict[str, Any]:
        with self.lock:
            job = self.get_job(job_id)
            job.update(fields)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            write_json(self._job_path(job_id), job)
            return job

    def _log(self, job_id: str, message: str) -> None:
        with self.lock:
            job = self.get_job(job_id)
            lines = list(job.get("log") or [])
            lines.append(f"{datetime.now(timezone.utc).isoformat()} {message}")
            job["log"] = lines[-80:]
            job["log_tail"] = "\n".join(job["log"][-12:])
            write_json(self._job_path(job_id), job)

    def start(
        self,
        basin_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        components: list[str] | None = None,
    ) -> dict[str, Any]:
        meta = self.catalog.get(basin_id)
        usgs = meta.get("usgs_site") or basin_id.replace("camels_", "")
        start = start or date.fromisoformat(meta.get("default_start") or "2019-05-03")
        end = end or date.fromisoformat(meta.get("default_end") or "2020-05-04")
        wanted = components or ["hydro", "gis", "dem"]
        job_id = f"dl-{uuid.uuid4().hex[:12]}"
        job = {
            "job_id": job_id,
            "basin_id": basin_id,
            "usgs_site": usgs,
            "status": "queued",
            "stage": "queued",
            "current_file": None,
            "bytes": 0,
            "fraction": 0.0,
            "components": wanted,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "error": None,
            "log": [],
            "log_tail": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json(self._job_path(job_id), job)
        self.pool.submit(self._run, job_id)
        return job

    def _run(self, job_id: str) -> None:
        try:
            job = self._update(job_id, status="running", stage="starting", fraction=0.02)
            basin_id = job["basin_id"]
            meta = self.catalog.get(basin_id)
            adapter = meta.get("adapter") or "multimet-legacy"
            usgs = job["usgs_site"]
            start = date.fromisoformat(job["start"])
            end = date.fromisoformat(job["end"])
            if adapter == "open-v1":
                self._run_open_v1(job_id, basin_id, usgs, start, end)
            else:
                wanted = set(job["components"])
                steps = [c for c in ("hydro", "gis", "dem") if c in wanted]
                for index, step in enumerate(steps):
                    base = index / max(len(steps), 1)
                    span = 1.0 / max(len(steps), 1)
                    if step == "hydro":
                        self._download_hydro(job_id, basin_id, usgs, start, end, base, span)
                    elif step == "gis":
                        self._download_gis(job_id, basin_id, usgs, base, span)
                    elif step == "dem":
                        self._download_dem(job_id, basin_id, base, span)
            self.catalog._refresh_catalog_status(basin_id)
            self._update(job_id, status="succeeded", stage="done", fraction=1.0, current_file=None)
            self._log(job_id, "download complete")
        except Exception as exc:  # noqa: BLE001 - surface to job record
            self._update(job_id, status="failed", error=str(exc), stage="failed")
            self._log(job_id, f"failed: {exc}")

    def _run_open_v1(
        self, job_id: str, basin_id: str, usgs: str, start: date, end: date
    ) -> None:
        from hydro_agent.data.adapters.open_basin import GaugeSpec, build_open_basin_case

        meta = self.catalog.get(basin_id)
        spec = GaugeSpec(
            usgs_site=usgs,
            basin_id=basin_id,
            label=str(meta.get("label") or basin_id),
            region=str(meta.get("region") or "USA"),
        )

        def progress(stage: str, current: str, frac: float) -> None:
            self._progress(job_id, stage=stage, current_file=current, fraction=frac)

        summary = build_open_basin_case(
            self.catalog.directory(basin_id),
            spec,
            start=start,
            end=end,
            progress=progress,
        )
        self._log(job_id, json.dumps({"open_v1_summary": summary}, ensure_ascii=False))
        self._update(job_id, stage="open_v1_summary", fraction=0.98, current_file=None)

    def _progress(
        self,
        job_id: str,
        *,
        stage: str,
        current_file: str | None,
        fraction: float,
        nbytes: int = 0,
    ) -> None:
        self._update(
            job_id,
            stage=stage,
            current_file=current_file,
            fraction=max(0.0, min(1.0, fraction)),
            bytes=nbytes,
        )
        if current_file:
            self._log(job_id, f"{stage}: {current_file}")

    def _fetch(self, url: str, destination: Path, job_id: str, stage: str, fraction: float) -> bytes:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._progress(job_id, stage=stage, current_file=destination.name, fraction=fraction)
        request = urllib.request.Request(url, headers={"User-Agent": "Hydro-Agent/0.1"})
        with urllib.request.urlopen(request, timeout=120) as response, destination.with_suffix(
            destination.suffix + ".part"
        ).open("wb") as stream:
            shutil.copyfileobj(response, stream)
            nbytes = stream.tell()
        part = destination.with_suffix(destination.suffix + ".part")
        part.replace(destination)
        self._progress(
            job_id,
            stage=stage,
            current_file=destination.name,
            fraction=min(1.0, fraction + 0.01),
            nbytes=nbytes,
        )
        return destination.read_bytes()

    def _download_hydro(
        self,
        job_id: str,
        basin_id: str,
        usgs_site: str,
        start: date,
        end: date,
        base: float,
        span: float,
    ) -> None:
        hydro = self.catalog.hydro_dir(basin_id)
        if hydro.exists():
            shutil.rmtree(hydro)
        hydro.mkdir(parents=True)
        raw = hydro / "raw"
        raw.mkdir()
        receipts: list[dict[str, Any]] = []
        retrieved = datetime.now(timezone.utc)

        def download(url: str, name: str, frac: float) -> bytes:
            data = self._fetch(url, raw / name, job_id, "multimet" if "zarr" in url or "storage.googleapis" in url else "usgs_flow", base + span * frac)
            receipts.append(
                dict(url=url, file=f"raw/{name}", sha256=sha256_file(raw / name), bytes=(raw / name).stat().st_size)
            )
            return data

        metadata = json.loads(download(MULTIMET_BASE + ".zmetadata", "zmetadata.json", 0.05).decode())["metadata"]
        attrs = metadata[".zattrs"]
        if "FAO_PENMAN_MONTEITH" not in attrs.get("Units", ""):
            raise ValueError("FAO PM units metadata missing")

        def chunk(variable: str, key: str, frac: float):
            info = metadata[variable + "/.zarray"]
            if info["filters"] is not None or info["order"] != "C":
                raise ValueError("unsupported Zarr layout")
            data = download(MULTIMET_BASE + variable + "/" + key, f"{variable}-{key}.bin", frac)
            decoded = get_codec(info["compressor"]).decode(data)
            return np.frombuffer(decoded, dtype=info["dtype"]).reshape(info["chunks"])

        basin_info = metadata["basin/.zarray"]
        basin_index = None
        chunk_count = (basin_info["shape"][0] + basin_info["chunks"][0] - 1) // basin_info["chunks"][0]
        for i in range(chunk_count):
            values = chunk("basin", str(i), 0.1 + 0.3 * i / max(chunk_count, 1))
            matches = np.flatnonzero(values == basin_id)
            if len(matches):
                basin_index = i * basin_info["chunks"][0] + int(matches[0])
                break
        if basin_index is None:
            raise ValueError(f"MultiMet 中找不到流域 {basin_id}")

        date_attrs = metadata["date/.zattrs"]
        if date_attrs["units"] != "days since 1950-01-01 00:00:00":
            raise ValueError("unexpected date origin")
        dates = [date(1950, 1, 1) + timedelta(days=int(v)) for v in chunk("date", "0", 0.45)]
        selected = [i for i, d in enumerate(dates) if start <= d <= end]
        if len(selected) != (end - start).days + 1:
            raise ValueError("incomplete source date coverage")

        series = {}
        for offset, key in enumerate(("total_precipitation", "potential_evaporation_FAO_PENMAN_MONTEITH")):
            variable = "era5land_" + key
            info = metadata[variable + "/.zarray"]
            values = chunk(variable, f"{basin_index // info['chunks'][0]}.0", 0.55 + 0.15 * offset)[
                basin_index % info["chunks"][0]
            ]
            series[key] = values[selected]

        site_url = f"https://waterservices.usgs.gov/nwis/site/?format=rdb&sites={usgs_site}&siteOutput=expanded"
        site_text = download(site_url, "usgs-site.rdb", 0.75).decode("utf-8")
        lines = [s for s in site_text.splitlines() if s and not s.startswith("#")]
        site = list(csv.DictReader([lines[0], *lines[2:]], delimiter="\t"))
        if len(site) != 1 or site[0]["site_no"] != usgs_site:
            raise ValueError("USGS station mismatch")
        area_km2 = float(site[0]["drain_area_va"]) * 2.589988110336
        lat = float(site[0]["dec_lat_va"])
        lon = float(site[0]["dec_long_va"])
        basin = dict(
            basin_id=basin_id,
            station_id=f"USGS-{usgs_site}",
            usgs_site=usgs_site,
            area_km2=area_km2,
            latitude=lat,
            longitude=lon,
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
        (hydro / "forcing.jsonl").write_text("\n".join(r.model_dump_json() for r in rows) + "\n", encoding="utf-8")
        flow_url = (
            f"https://waterservices.usgs.gov/nwis/dv/?format=json&sites={usgs_site}"
            f"&parameterCd=00060&siteStatus=all&startDT={start.isoformat()}&endDT={end.isoformat()}"
        )
        flow_payload = json.loads(download(flow_url, "usgs-dv-00060.json", 0.9).decode("utf-8"))
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
            raise ValueError("insufficient USGS daily discharge")
        (hydro / "flow.jsonl").write_text("\n".join(r.model_dump_json() for r in flow_rows) + "\n", encoding="utf-8")
        (hydro / "basin.json").write_text(json.dumps(basin, sort_keys=True), encoding="utf-8")
        (hydro / "source-manifest.json").write_text(
            json.dumps(
                dict(
                    source="Caravan MultiMet + USGS NWIS DV",
                    basin_index=basin_index,
                    retrieved_at=retrieved.isoformat(),
                    raw_files=receipts,
                    latitude=lat,
                    longitude=lon,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        # Keep site coords for GIS/DEM steps.
        write_json(hydro / "outlet.json", dict(latitude=lat, longitude=lon, area_km2=area_km2, usgs_site=usgs_site))
        self._progress(job_id, stage="hydro", current_file="forcing.jsonl", fraction=base + span)

    def _download_gis(self, job_id: str, basin_id: str, usgs_site: str, base: float, span: float) -> None:
        hydro = self.catalog.hydro_dir(basin_id)
        outlet_path = hydro / "outlet.json"
        if not outlet_path.is_file():
            # Derive from basin.json if hydro came from legacy copy.
            basin = json.loads((hydro / "basin.json").read_text(encoding="utf-8"))
            if "latitude" not in basin:
                raise ValueError("缺少测站坐标，请先重新下载水文资料")
            write_json(
                outlet_path,
                dict(
                    latitude=basin["latitude"],
                    longitude=basin["longitude"],
                    area_km2=basin["area_km2"],
                    usgs_site=usgs_site,
                ),
            )
        outlet = json.loads(outlet_path.read_text(encoding="utf-8"))
        lat, lon = float(outlet["latitude"]), float(outlet["longitude"])
        area = float(outlet["area_km2"])
        # Approximate catchment radius (km) from area; convert to degrees.
        radius_km = max(5.0, math.sqrt(area / math.pi))
        deg = radius_km / 111.0
        ring = []
        for i in range(33):
            ang = 2 * math.pi * i / 32
            ring.append([lon + deg * math.cos(ang) / max(math.cos(math.radians(lat)), 0.2), lat + deg * math.sin(ang)])
        gis = self.catalog.gis_dir(basin_id)
        if gis.exists():
            shutil.rmtree(gis)
        gis.mkdir(parents=True)
        boundary = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"basin_id": basin_id, "approximation": "equal-area-circle"},
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
            ],
        }
        outlet_fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"usgs_site": usgs_site, "name": "outlet"},
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            ],
        }
        self._progress(job_id, stage="gis", current_file="boundary.geojson", fraction=base + span * 0.5)
        write_json(gis / "boundary.geojson", boundary)
        write_json(gis / "outlet.geojson", outlet_fc)
        write_json(
            gis / "bbox.json",
            dict(west=lon - deg * 1.2, south=lat - deg * 1.2, east=lon + deg * 1.2, north=lat + deg * 1.2),
        )
        self._progress(job_id, stage="gis", current_file="outlet.geojson", fraction=base + span)

    def _download_dem(self, job_id: str, basin_id: str, base: float, span: float) -> None:
        gis = self.catalog.gis_dir(basin_id)
        bbox_path = gis / "bbox.json"
        if not bbox_path.is_file():
            raise ValueError("缺少 GIS bbox，请先下载边界")
        bbox = json.loads(bbox_path.read_text(encoding="utf-8"))
        west, south, east, north = bbox["west"], bbox["south"], bbox["east"], bbox["north"]
        pad = 0.05
        west, south, east, north = west - pad, south - pad, east + pad, north + pad
        jobs = [
            (lat, lon)
            for lat in range(math.floor(south), math.ceil(north))
            for lon in range(math.floor(west), math.ceil(east))
        ]
        dem = self.catalog.dem_dir(basin_id)
        dem.mkdir(parents=True, exist_ok=True)
        records = []
        for index, (lat, lon) in enumerate(jobs):
            tile = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/skadi/{tile[:3]}/{tile}.hgt.gz"
            packed = dem / f"{tile}.hgt.gz"
            frac = base + span * (index + 1) / max(len(jobs), 1)
            if not packed.is_file():
                self._fetch(url, packed, job_id, "dem_tiles", frac)
            with gzip.open(packed, "rb") as stream:
                payload = stream.read()
            size = math.isqrt(len(payload) // 2)
            if size not in (1201, 3601) or len(payload) != size * size * 2:
                raise ValueError(f"Invalid HGT dimensions: {packed}")
            hgt = dem / f"{tile}.hgt"
            hgt.write_bytes(payload)
            records.append(
                dict(
                    file=packed.name,
                    url=url,
                    sha256=sha256_file(packed),
                    hgt_sha256=sha256_file(hgt),
                    bytes=packed.stat().st_size,
                    samples_per_side=size,
                    latitude=lat,
                    longitude=lon,
                )
            )
            self._progress(job_id, stage="dem_tiles", current_file=packed.name, fraction=frac, nbytes=packed.stat().st_size)
        write_json(
            dem / "sources.json",
            dict(
                provider="Mapzen / Tilezen Terrain Tiles, AWS public bucket",
                download_bbox_wgs84=[west, south, east, north],
                tiles=records,
                attribution="SRTM data courtesy of the U.S. Geological Survey.",
            ),
        )
