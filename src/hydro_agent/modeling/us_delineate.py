"""DEM → pyflwdir catchment partition for open (US) basins.

Mirrors Yaogu ``dem_xaj_lab.delineate`` semantics: Skadi/GeoTIFF mosaic → D8 →
``subbasins_area`` inside the gauge catchment. Reference geometry comes from
NLDI ``boundary.geojson`` and the USGS outlet point, not Chinese station layers.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _dump(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def _load_reference_polygon(boundary_geojson: Path):
    from shapely.geometry import shape
    from shapely.ops import unary_union

    payload = json.loads(boundary_geojson.read_text(encoding="utf-8"))
    features = payload.get("features") or ([payload] if payload.get("geometry") else [])
    geoms = [shape(f["geometry"]) for f in features if f.get("geometry")]
    if not geoms:
        raise ValueError("boundary.geojson has no geometry")
    return unary_union(geoms)


def _outlet_wgs84(outlet_geojson: Path) -> tuple[float, float]:
    payload = json.loads(outlet_geojson.read_text(encoding="utf-8"))
    for feature in payload.get("features") or []:
        geom = feature.get("geometry") or {}
        if geom.get("type") == "Point":
            lon, lat = geom["coordinates"][:2]
            return float(lon), float(lat)
    raise ValueError("outlet.geojson must contain a Point feature")


def _mosaic_skadi(dem_dir: Path, sources: dict[str, Any], grid, height: int, width: int, crs: str):
    import numpy as np
    import rasterio
    from rasterio.warp import reproject, Resampling

    dem = np.full((height, width), -32768, dtype="float32")
    for record in sources["tiles"]:
        packed_name = record["file"]
        hgt = dem_dir / packed_name.removesuffix(".gz")
        packed = dem_dir / packed_name
        if not hgt.is_file():
            if not packed.is_file():
                raise FileNotFoundError(f"Missing DEM tile: {packed_name}")
            import gzip

            hgt.write_bytes(gzip.open(packed, "rb").read())
        gz_hash = record.get("sha256")
        if gz_hash and packed.is_file() and _sha256(packed) != gz_hash:
            raise ValueError(f"DEM gz hash mismatch: {packed}")
        hgt_hash = record.get("hgt_sha256")
        if hgt_hash and _sha256(hgt) != hgt_hash:
            raise ValueError(f"DEM hgt hash mismatch: {hgt}")
        with rasterio.open(hgt) as src:
            reproject(
                rasterio.band(src, 1),
                dem,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=-32768,
                dst_transform=grid,
                dst_crs=crs,
                dst_nodata=-32768,
                init_dest_nodata=False,
                resampling=Resampling.average,
            )
    return dem


def _mosaic_geotiff(
    dem_dir: Path,
    sources: dict[str, Any],
    grid,
    height: int,
    width: int,
    crs: str,
):
    import numpy as np
    import rasterio
    from rasterio.warp import reproject, Resampling

    relative = (sources.get("downloaded") or {}).get("file") or ""
    # Manifest stores paths like "dem/leaf_river_3dep_30m.tif" or just the filename.
    candidates = [
        dem_dir / Path(relative).name,
        dem_dir / relative,
        dem_dir.parent / relative,
    ]
    tif = next((p for p in candidates if p.is_file()), None)
    if tif is None:
        raise FileNotFoundError(f"GeoTIFF DEM not found for {relative!r}")
    dem = np.full((height, width), -32768, dtype="float32")
    with rasterio.open(tif) as src:
        reproject(
            rasterio.band(src, 1),
            dem,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=grid,
            dst_crs=crs,
            dst_nodata=-32768,
            init_dest_nodata=False,
            resampling=Resampling.average,
        )
    return dem


def delineate_open_basin(
    *,
    dem_dir: Path,
    source_gis: Path,
    case_dir: Path,
    resolution_m: float = 90.0,
    stream_area_km2: float = 50.0,
    unit_area_km2: float = 50.0,
    snap_distance_m: float = 2000.0,
    min_iou: float = 0.7,
    model_mode: str = "distributed",
) -> dict[str, Any]:
    """Partition an open basin into pyflwdir units; write ``case_dir/gis`` artifacts."""

    import numpy as np
    import pandas as pd
    import pyflwdir
    from pyproj import Transformer
    from rasterio.features import geometry_mask, shapes
    from rasterio.transform import from_origin
    from rasterio.warp import transform_bounds
    from shapely.geometry import mapping, shape
    from shapely.ops import transform as geom_transform

    from hydro_agent.models.xaj.vendor.dem_xaj_lab import (
        flow_from_dem,
        merge_units,
        partition_catchment,
        stage,
        write_raster,
    )

    if resolution_m <= 0 or stream_area_km2 <= 0 or unit_area_km2 <= 0 or snap_distance_m <= 0:
        raise ValueError("resolution, stream area, unit area, and snap radius must be positive")
    if not 0 < min_iou <= 1:
        raise ValueError("min_iou must be in (0, 1]")
    if model_mode not in {"distributed", "lumped"}:
        raise ValueError(f"unsupported model_mode: {model_mode}")

    dem_dir = Path(dem_dir).resolve()
    source_gis = Path(source_gis).resolve()
    case_dir = Path(case_dir).resolve()
    boundary_path = source_gis / "boundary.geojson"
    outlet_path = source_gis / "outlet.geojson"
    sources_path = dem_dir / "sources.json"
    if not boundary_path.is_file():
        raise FileNotFoundError("缺少 boundary.geojson")
    if not outlet_path.is_file():
        raise FileNotFoundError("缺少 outlet.geojson")
    if not sources_path.is_file():
        raise FileNotFoundError("缺少 dem/sources.json；请先下载 DEM")

    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    if sources.get("tiles"):
        west, south, east, north = sources["download_bbox_wgs84"]
        dem_backend = "skadi"
    elif sources.get("downloaded", {}).get("file") or sources.get("bounds"):
        bounds = sources.get("bounds") or sources.get("download_bbox_wgs84")
        if not bounds or len(bounds) != 4:
            raise ValueError("GeoTIFF DEM sources.json missing bounds")
        west, south, east, north = bounds
        dem_backend = "geotiff"
    else:
        raise ValueError(
            "DEM sources.json 无法识别：需要 Skadi tiles 或 GeoTIFF downloaded 记录"
        )

    case_dir.mkdir(parents=True, exist_ok=True)
    gis = case_dir / "gis"
    if gis.exists():
        shutil.rmtree(gis)
    gis.mkdir()

    epsg = 32600 + int(((west + east) / 2 + 180) / 6) + 1
    if south < 0:
        epsg += 100
    crs = f"EPSG:{epsg}"
    left, bottom, right, top = transform_bounds("EPSG:4326", crs, west, south, east, north)
    resolution = float(resolution_m)
    grid = from_origin(
        math.floor(left / resolution) * resolution,
        math.ceil(top / resolution) * resolution,
        resolution,
        resolution,
    )
    width = math.ceil((right - grid.c) / resolution)
    height = math.ceil((grid.f - bottom) / resolution)
    if width < 8 or height < 8:
        raise ValueError(f"Projected DEM grid too small: {width}x{height}")

    stage(gis, "mosaic DEM", backend=dem_backend, crs=crs, resolution_m=resolution)
    if dem_backend == "skadi":
        dem = _mosaic_skadi(dem_dir, sources, grid, height, width, crs)
    else:
        dem = _mosaic_geotiff(dem_dir, sources, grid, height, width, crs)
    if np.any(dem == -32768) or not np.isfinite(dem).all():
        # Soft-fill residual voids with local median so legacy padded 3DEP exports can proceed.
        void = (dem == -32768) | ~np.isfinite(dem)
        if void.all():
            raise ValueError("DEM mosaic is empty")
        fill_value = float(np.nanmedian(np.where(void, np.nan, dem)))
        dem = np.where(void, fill_value, dem).astype("float32")

    profile = dict(height=height, width=width, crs=crs, transform=grid)
    write_raster(gis / "dem_projected.tif", dem, profile, -32768)
    stage(gis, "fill_depressions / D8 / accumulation", version=pyflwdir.__version__)
    filled, d8, flow, accumulation = flow_from_dem(dem, grid)
    write_raster(gis / "dem_filled.tif", filled, profile, -32768)
    write_raster(gis / "d8_pointer.tif", d8, profile, 247)
    write_raster(gis / "accumulation.tif", accumulation, profile, -9999)
    streams = accumulation * resolution**2 / 1e6 >= stream_area_km2
    write_raster(gis / "streams.tif", streams.astype("uint8"), profile)
    stage(gis, "streams / bounded outlet search", stream_area_km2=stream_area_km2)

    forward = Transformer.from_crs(4326, crs, always_xy=True)
    inverse = Transformer.from_crs(crs, 4326, always_xy=True)
    reference = geom_transform(forward.transform, _load_reference_polygon(boundary_path))
    ref_mask = geometry_mask([mapping(reference)], (height, width), grid, invert=True)
    lon, lat = _outlet_wgs84(outlet_path)
    sx, sy = forward.transform(lon, lat)
    rows, cols = np.indices(dem.shape)
    xs = grid.c + (cols + 0.5) * resolution
    ys = grid.f - (rows + 0.5) * resolution
    distance = np.hypot(xs - sx, ys - sy)
    candidates = (distance <= snap_distance_m) & ref_mask
    if not candidates.any():
        raise ValueError("Outlet search radius does not intersect reference basin")
    flat_index = int(np.argmax(np.where(candidates, accumulation, -np.inf)))
    rr, cc = np.unravel_index(flat_index, dem.shape)
    pours = np.zeros(dem.shape, dtype="int32")
    pours[rr, cc] = 1
    write_raster(gis / "outlet.tif", pours, profile)
    stage(gis, "basins / subbasins_area", unit_area_km2=unit_area_km2)

    basin, labels, unit_outlets, local_flow = partition_catchment(
        d8, flow, flat_index, grid, unit_area_km2
    )
    write_raster(gis / "catchment.tif", basin.astype("int32"), profile)
    intersection = int(np.count_nonzero(basin & ref_mask))
    union = int(np.count_nonzero(basin | ref_mask))
    iou = intersection / union if union else 0.0
    check = dict(
        outlet_wgs84=[lon, lat],
        snapped_wgs84=list(inverse.transform(xs[rr, cc], ys[rr, cc])),
        snap_distance_m=float(distance[rr, cc]),
        search_radius_m=snap_distance_m,
        dem_area_km2=float(basin.sum() * resolution**2 / 1e6),
        reference_area_km2=float(reference.area / 1e6),
        intersection_over_union=iou,
        touches_dem_edge=bool(
            basin[0].any() or basin[-1].any() or basin[:, 0].any() or basin[:, -1].any()
        ),
        accepted=False,
        human_review_required=True,
        dem_backend=dem_backend,
        note=(
            "DEM catchment vs NLDI reference. Inspect outlet snap and unit polygons before confirming."
        ),
    )
    _dump(gis / "boundary_check.json", check)
    if check["intersection_over_union"] < min_iou:
        raise ValueError(f"Outlet/catchment needs manual review: {check}; no model inputs built")
    # Edge contact is recorded for the review map; open DEM mosaics are often tight
    # around the NLDI bbox, so we do not hard-fail when IoU already clears the bar.
    check["accepted"] = True
    _dump(gis / "boundary_check.json", check)

    old_ids = np.unique(labels[basin])
    if len(old_ids) < 2 and model_mode != "lumped":
        raise ValueError("Only one unit; reduce unit_area_km2")
    units = np.zeros(dem.shape, dtype="int32")
    records = []
    for uid, old in enumerate(old_ids, 1):
        mask = basin & (labels == old)
        units[mask] = uid
        records.append(
            dict(
                unit_id=uid,
                source_basin_id=int(old),
                cells=int(mask.sum()),
                area_km2=float(mask.sum() * resolution**2 / 1e6),
                mean_elevation_m=float(dem[mask].mean()),
                source="pyflwdir-subbasins_area",
            )
        )
    write_raster(gis / "units.tif", units, profile)
    pd.DataFrame(records).to_csv(gis / "units.csv", index=False)

    network = []
    for idx in unit_outlets:
        uid = int(units.flat[idx])
        downstream_idx = int(local_flow.idxs_ds[idx])
        downstream_uid = int(units.flat[downstream_idx]) if downstream_idx != idx else 0
        if downstream_uid == uid:
            raise ValueError("Unit outlet must flow to a different unit or terminate")
        network.append(
            dict(
                unit_id=uid,
                downstream_unit_id=downstream_uid,
                outlet_index=int(idx),
                outlet_wgs84=list(inverse.transform(xs.flat[idx], ys.flat[idx])),
            )
        )
    _dump(gis / "unit_topology.json", network)

    river_features = flow.streams(mask=streams & basin)
    for feature in river_features:
        feature["geometry"] = mapping(
            geom_transform(inverse.transform, shape(feature["geometry"]))
        )
        feature["properties"] = {
            key: value.item() if isinstance(value, np.generic) else value
            for key, value in feature["properties"].items()
        }
    _dump(gis / "streams.geojson", dict(type="FeatureCollection", features=river_features))

    features = []
    for geometry, value in shapes(units, mask=basin, transform=grid):
        geometry = geom_transform(inverse.transform, shape(geometry))
        features.append(
            dict(
                type="Feature",
                properties={"unit_id": int(value), "label": f"U{int(value)}"},
                geometry=mapping(geometry),
            )
        )
    _dump(gis / "units.geojson", dict(type="FeatureCollection", features=features))
    _dump(
        gis / "reference_boundary.geojson",
        dict(
            type="FeatureCollection",
            features=[
                dict(
                    type="Feature",
                    properties={},
                    geometry=mapping(_load_reference_polygon(boundary_path)),
                )
            ],
        ),
    )
    # Keep NLDI review layers alongside DEM products.
    for name in ("boundary.geojson", "outlet.geojson", "bbox.json", "flowlines.geojson", "nldi_feature.json"):
        src = source_gis / name
        if src.is_file() and not (gis / name).is_file():
            shutil.copy2(src, gis / name)

    source_dir = case_dir / "source_dem"
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir()
    shutil.copy2(sources_path, source_dir / "sources.json")
    if dem_backend == "skadi":
        for record in sources["tiles"]:
            packed = dem_dir / record["file"]
            if packed.is_file():
                shutil.copy2(packed, source_dir / packed.name)
    else:
        relative = (sources.get("downloaded") or {}).get("file") or ""
        tif = dem_dir / Path(relative).name
        if tif.is_file():
            shutil.copy2(tif, source_dir / tif.name)

    dem_config = dict(
        resolution_m=resolution,
        crs=crs,
        model_mode="distributed",
        stream_area_km2=stream_area_km2,
        unit_area_km2=unit_area_km2,
        min_iou=min_iou,
        boundary_check=check,
        unit_count=len(records),
        backend="pyflwdir",
        backend_version=pyflwdir.__version__,
        dem_source=dem_backend,
        d8_encoding="ESRI / PyFlwDir: pit=0, nodata=247",
        partition_method=(
            "subbasins_area within selected gauge catchment; threshold is km2, not fixed unit count"
        ),
        routing=(
            "Each disjoint unit independently routed to the common outlet by native xaj.Model; "
            "not a river-network cascade."
        ),
    )
    _dump(case_dir / "dem_config.json", dem_config)
    if model_mode == "lumped":
        merge_units(case_dir)
        dem_config = json.loads((case_dir / "dem_config.json").read_text(encoding="utf-8"))

    units_csv = list(pd.read_csv(gis / "units.csv").to_dict(orient="records"))
    return dict(
        dem_config=dem_config,
        boundary_check=check,
        unit_count=len(units_csv),
        area_km2=float(check["dem_area_km2"]),
        units=units_csv,
    )
