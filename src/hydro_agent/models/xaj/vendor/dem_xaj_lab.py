#!/usr/bin/env python3
"""Real DEM -> disjoint units -> native multi-unit XAJ, without an Agent.

Run download, delineate, build separately so each modelling choice is auditable.
No credentials or .env files are used. See tutorials/XAJ_DEM_DISTRIBUTED_TUTORIAL.md.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "examples" / "data"
DEM = ROOT / "examples" / "dem" / "yaogu"


def dump(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def sha256(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def boundary(raw):
    import fiona
    from rasterio.crs import CRS
    from shapely.geometry import shape
    from shapely.ops import unary_union
    # Geometry only: legacy DBF field names have broken mixed encodings.
    with fiona.open(raw / "GIS图层" / "分区.shp", encoding="latin1") as source:
        if CRS.from_user_input(source.crs).to_epsg() != 4326:
            raise ValueError("This case expects the reference boundary in EPSG:4326")
        return unary_union([shape(f["geometry"]) for f in source])


def download(args):
    """Download immutable local copies of the public Skadi tiles with checksums."""
    import numpy as np
    target = args.dem.resolve()
    target.mkdir(parents=True, exist_ok=True)
    west, south, east, north = boundary(args.raw).bounds
    bbox = [west - .05, south - .05, east + .05, north + .05]
    jobs = [(lat, lon) for lat in range(math.floor(bbox[1]), math.ceil(bbox[3]))
            for lon in range(math.floor(bbox[0]), math.ceil(bbox[2]))]

    def fetch(job):
        lat, lon = job
        tile = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
        url = f"https://s3.amazonaws.com/elevation-tiles-prod/skadi/{tile[:3]}/{tile}.hgt.gz"
        packed = target / f"{tile}.hgt.gz"
        previous = {}
        if (target / "sources.json").exists():
            previous = {x["file"]: x for x in json.loads((target / "sources.json").read_text())["tiles"]}
        reused = packed.exists()
        if reused and packed.name in previous and sha256(packed) != previous[packed.name]["sha256"]:
            raise ValueError(f"Cached DEM checksum mismatch: {packed}")
        if not reused:
            print(f"Downloading {url}", flush=True)
            request = urllib.request.Request(url, headers={"User-Agent": "XAJ-academy/1.0"})
            with urllib.request.urlopen(request, timeout=120) as response, packed.with_suffix(".part").open("wb") as stream:
                shutil.copyfileobj(response, stream)
            packed.with_suffix(".part").replace(packed)
        with gzip.open(packed, "rb") as stream:
            payload = stream.read()
        size = math.isqrt(len(payload) // 2)
        if size not in (1201, 3601) or len(payload) != size * size * 2:
            raise ValueError(f"Invalid HGT dimensions: {packed}")
        if not np.any(np.frombuffer(payload, dtype=">i2") != -32768):
            raise ValueError(f"Empty DEM: {packed}")
        hgt = target / f"{tile}.hgt"
        hgt.write_bytes(payload)
        return dict(file=packed.name, url=url, sha256=sha256(packed), hgt_sha256=sha256(hgt),
                    bytes=packed.stat().st_size, samples_per_side=size, arcseconds=3600/(size-1),
                    latitude=lat, longitude=lon, downloaded_utc=previous.get(packed.name, {}).get(
                        "downloaded_utc", datetime.now(timezone.utc).isoformat()))

    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(fetch, jobs))
    dump(target / "sources.json", dict(provider="Mapzen / Tilezen Terrain Tiles, AWS public bucket",
        reference_bbox_wgs84=list(boundary(args.raw).bounds), download_bbox_wgs84=bbox,
        attribution="Terrain Tiles contains blended elevation sources; SRTM data courtesy of the U.S. Geological Survey. Not a surveyed bare-earth DTM.",
        documentation="https://github.com/tilezen/joerd/blob/master/docs/attribution.md", tiles=records))
    print(f"Downloaded and verified {len(records)} tiles: {target}")


def stage(work, name, **details):
    print(f"PyFlwDir: {name}", flush=True)
    with (work / "processing.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(dict(time_utc=datetime.now(timezone.utc).isoformat(),
                                     stage=name, **details), ensure_ascii=False) + "\n")


def flow_from_dem(dem, transform):
    """Fill depressions and resolve drainage in-process; D8 uses ESRI encoding."""
    import numpy as np
    import pyflwdir
    if not np.isfinite(dem).all() or np.any(dem == -32768):
        raise ValueError("DEM must have complete finite elevation coverage")
    filled, d8 = pyflwdir.dem.fill_depressions(dem, nodata=-32768, outlets="edge")
    flow = pyflwdir.from_array(d8, ftype="d8", transform=transform, latlon=False)
    if not flow.isvalid:
        raise ValueError("Invalid/cyclic flow directions")
    accumulation = flow.accuflux(np.ones(dem.shape, dtype="float64"))
    return filled, d8, flow, accumulation


def partition_catchment(d8, flow, outlet_index, transform, min_area_km2):
    """Partition the gauge catchment itself, not clipped nested total basins."""
    import numpy as np
    import pyflwdir
    basin = flow.basins(idxs=np.array([outlet_index])) > 0
    local_d8 = d8.copy()
    local_d8[~basin] = 247  # PyFlwDir's D8 missing-value encoding, not Whitebox.
    local_d8.flat[outlet_index] = 0  # Make the selected gauge the terminal pit.
    local_flow = pyflwdir.from_array(local_d8, ftype="d8", transform=transform, latlon=False)
    if not local_flow.isvalid or set(local_flow.idxs_pit.tolist()) != {int(outlet_index)}:
        raise ValueError("Selected catchment must drain to exactly one outlet")
    labels, outlets = local_flow.subbasins_area(min_area_km2)
    if np.any(labels[basin] <= 0) or np.any(labels[~basin] != 0):
        raise ValueError("Subbasins must cover exactly the selected catchment")
    return basin, labels, outlets, local_flow


def write_raster(path, values, profile, nodata=0):
    import rasterio
    info = profile.copy()
    info.update(driver="GTiff", count=1, dtype=values.dtype, nodata=nodata, compress="deflate")
    with rasterio.open(path, "w", **info) as target:
        target.write(values, 1)


def merge_units(case):
    """Merge a prepared GIS partition; rebuild forcing later, never sum hydrographs."""
    import numpy as np
    import pandas as pd
    import rasterio
    from shapely.geometry import shape, mapping
    from shapely.ops import unary_union
    case = Path(case).resolve()
    if (case / "model_inputs").exists():
        raise ValueError("Merge into a new preparation case, never mutate built model inputs")
    gis = case / "gis"
    config = json.loads((case / "dem_config.json").read_text(encoding="utf-8"))
    if config.get("model_mode") == "lumped":
        raise ValueError("Already lumped; select the original distributed case")
    table = pd.read_csv(gis / "units.csv")
    with rasterio.open(gis / "units.tif") as src:
        labels, profile = src.read(1), src.profile
    with rasterio.open(gis / "catchment.tif") as src:
        basin = src.read(1) > 0
    if not np.array_equal(labels > 0, basin):
        raise ValueError("Unit coverage differs from catchment")
    ids, counts = np.unique(labels[basin], return_counts=True)
    area = counts * abs(profile["transform"].determinant) / 1e6
    if not np.array_equal(ids, table.unit_id) or not np.allclose(area, table.area_km2):
        raise ValueError("Source unit table/raster mismatch")
    if not np.isclose(area.sum(), config["boundary_check"]["dem_area_km2"]):
        raise ValueError("Source area does not match accepted catchment")
    archive = gis / "original_subbasins"
    archive.mkdir(exist_ok=False)
    for name in ("units.tif", "units.csv", "units.geojson", "unit_topology.json"):
        shutil.copy2(gis / name, archive / name)
    write_raster(gis / "units.tif", basin.astype("int32"), profile)
    with rasterio.open(gis / "dem_projected.tif") as src:
        elevation = float(src.read(1)[basin].mean())
    pd.DataFrame([dict(unit_id=1, source_basin_id=0, cells=int(basin.sum()),
                      area_km2=float(area.sum()), mean_elevation_m=elevation)]).to_csv(gis / "units.csv", index=False)
    original = json.loads((archive / "units.geojson").read_text(encoding="utf-8"))
    merged = unary_union([shape(f["geometry"]) for f in original["features"]])
    dump(gis / "units.geojson", dict(type="FeatureCollection", features=[dict(
        type="Feature", properties={"unit_id": 1}, geometry=mapping(merged))]))
    topology = json.loads((archive / "unit_topology.json").read_text(encoding="utf-8"))
    terminal = [r for r in topology if r["downstream_unit_id"] == 0]
    if len(terminal) != 1:
        raise ValueError("Expected exactly one common outlet")
    dump(gis / "unit_topology.json", [dict(terminal[0], unit_id=1, downstream_unit_id=0)])
    pd.DataFrame(dict(source_unit_id=ids, merged_unit_id=np.ones(len(ids), dtype=int),
                      area_km2=area, area_fraction=area/area.sum())).to_csv(gis / "merge_mapping.csv", index=False)
    config.update(model_mode="lumped", unit_count=1, original_unit_count=len(ids),
                  partition_method="Union of all delineated subbasins; one full-catchment unit",
                  routing="One full-area native XAJ unit to the common outlet; forcing rebuilt by catchment Thiessen weights")
    dump(case / "dem_config.json", config)


def render_map(case, raw=RAW, output=None):
    """Offline map with extracted streams, source hydrography and review landmarks."""
    import fiona
    import numpy as np
    import pandas as pd
    import rasterio
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform as geom_transform
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.colors import LightSource
    case, raw = Path(case), Path(raw)
    gis = case / "gis"
    output = Path(output) if output else gis / "units_map.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(gis / "dem_projected.tif") as src:
        dem, crs, grid, bounds = src.read(1), src.crs, src.transform, src.bounds
    with rasterio.open(gis / "units.tif") as src:
        units = src.read(1)
    transform = Transformer.from_crs(4326, crs, always_xy=True)
    fig, ax = plt.subplots(figsize=(10, 10))
    extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
    hill = LightSource(azdeg=315, altdeg=45).hillshade(dem, dx=abs(grid.a), dy=abs(grid.e))
    ax.imshow(hill, extent=extent, cmap="gray", alpha=.5)
    ax.imshow(np.ma.masked_equal(units, 0), extent=extent, cmap="tab20", alpha=.3, interpolation="nearest")
    handles, layers = [], {}

    def draw(geometry, color, width, style="-"):
        if geometry.geom_type in {"LineString", "LinearRing"}:
            ax.plot(*geometry.xy, color=color, linewidth=width, linestyle=style)
        elif geometry.geom_type == "Polygon":
            draw(geometry.exterior, color, width, style)
            for ring in geometry.interiors:
                draw(ring, color, width, style)
        elif hasattr(geometry, "geoms"):
            for part in geometry.geoms:
                draw(part, color, width, style)

    for name, color, width, style, label in [
        ("units.geojson", "#555555", .7, "-", "Model unit boundary"),
        ("reference_boundary.geojson", "black", 1.2, "--", "Reference basin boundary"),
        ("streams.geojson", "#087fc1", 1.3, "-", "DEM extracted streams")]:
        features = json.loads((gis / name).read_text(encoding="utf-8"))["features"]
        for feature in features:
            draw(geom_transform(transform.transform, shape(feature["geometry"])), color, width, style)
        layers[name] = len(features)
        handles.append(Line2D([], [], color=color, linewidth=width, linestyle=style, label=label))
    rivers = raw / "GIS图层/流域河网.shp"
    if not rivers.is_file():
        rivers = case / "raw_data/GIS图层/流域河网.shp"
    if rivers.is_file():
        with fiona.open(rivers, encoding="latin1") as src:
            if not src.crs:
                raise ValueError("Reference rivers need a known CRS")
            river_transform = Transformer.from_crs(src.crs, crs, always_xy=True)
            count = 0
            for feature in src:
                draw(geom_transform(river_transform.transform, shape(feature["geometry"])), "#702cb1", .9, "--")
                count += 1
        layers["reference_rivers"] = count
        handles.append(Line2D([], [], color="#702cb1", linestyle="--", label="Reference river network"))
    station_file = raw / "ST_STNM.xlsx"
    if not station_file.is_file():
        station_file = case / "raw_data/ST_STNM.xlsx"
    stations = pd.read_excel(station_file)
    sx, sy = transform.transform(stations["经度"].to_numpy(), stations["纬度"].to_numpy())
    handles.append(ax.scatter(sx, sy, s=24, color="#e88700", edgecolors="white", label="Station table gauges", zorder=8))
    for i, (x, y) in enumerate(zip(sx, sy), 1):
        ax.annotate(f"S{i}", (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7)
    check = json.loads((gis / "boundary_check.json").read_text(encoding="utf-8"))
    for key, marker, color, label in [("original_wgs84", "x", "red", "Selected station outlet"),
                                    ("station_gis_wgs84", "+", "magenta", "GIS station outlet"),
                                    ("snapped_wgs84", "*", "red", "DEM snapped outlet")]:
        if check.get(key):
            handles.append(ax.scatter(*transform.transform(*check[key]), marker=marker, color=color,
                                      s=100, label=label, zorder=10))
    for uid in np.unique(units[units > 0]):
        rows, cols = np.nonzero(units == uid)
        ax.text(grid.c+(cols.mean()+.5)*grid.a, grid.f+(rows.mean()+.5)*grid.e, f"U{uid}", fontsize=9,
                ha="center", bbox=dict(facecolor="white", alpha=.7, edgecolor="none"))
    rows, cols = np.nonzero(units)
    pad = .07 * max((cols.max()-cols.min())*abs(grid.a), (rows.max()-rows.min())*abs(grid.e))
    ax.set_xlim(grid.c+cols.min()*grid.a-pad, grid.c+(cols.max()+1)*grid.a+pad)
    ax.set_ylim(grid.f+(rows.max()+1)*grid.e-pad, grid.f+rows.min()*grid.e+pad)
    nzone = len(np.unique(units[units > 0]))
    ax.set(title=f"Yaogu: {'lumped' if nzone == 1 else 'distributed'} XAJ / {nzone} model unit(s)",
           xlabel=f"Easting (m), {crs}", ylabel="Northing (m)", aspect="equal")
    ax.legend(handles=handles, fontsize=7, loc="upper left")
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)
    return dict(output=output.name, layers=layers, station_labels="S1..Sn in ST_STNM.xlsx row order", unit_count=nzone)


def delineate(args):
    import fiona
    import numpy as np
    import pandas as pd
    import rasterio
    import pyflwdir
    from rasterio.features import geometry_mask, shapes
    from rasterio.transform import from_origin
    from rasterio.warp import reproject, Resampling, transform_bounds
    from pyproj import Transformer
    from shapely.geometry import mapping, shape
    from shapely.ops import transform as geom_transform

    case = args.case_dir.resolve()
    case.mkdir(parents=True, exist_ok=True)
    gis = case / "gis"
    # Never combine products of different thresholds/resolutions in one case.
    gis.mkdir(exist_ok=False)
    sources = json.loads((args.dem / "sources.json").read_text(encoding="utf-8"))
    west, south, east, north = sources["download_bbox_wgs84"]
    epsg = 32600 + int(((west + east) / 2 + 180) / 6) + 1
    if south < 0:
        epsg += 100
    crs = f"EPSG:{epsg}"
    left, bottom, right, top = transform_bounds("EPSG:4326", crs, west, south, east, north)
    resolution = args.resolution
    grid = from_origin(math.floor(left/resolution)*resolution, math.ceil(top/resolution)*resolution, resolution, resolution)
    width = math.ceil((right-grid.c)/resolution)
    height = math.ceil((grid.f-bottom)/resolution)
    dem = np.full((height, width), -32768, dtype="float32")
    for record in sources["tiles"]:
        hgt = args.dem / record["file"].removesuffix(".gz")
        if sha256(hgt) != record["hgt_sha256"]:
            raise ValueError(f"DEM hash mismatch: {hgt}")
        with rasterio.open(hgt) as src:
            reproject(rasterio.band(src, 1), dem, src_transform=src.transform, src_crs=src.crs,
                      src_nodata=-32768, dst_transform=grid, dst_crs=crs, dst_nodata=-32768,
                      init_dest_nodata=False, resampling=Resampling.average)
    if np.any(dem == -32768) or not np.isfinite(dem).all():
        raise ValueError("DEM mosaic has voids; fill/expand source coverage before routing")
    profile = dict(height=height, width=width, crs=crs, transform=grid)
    write_raster(gis / "dem_projected.tif", dem, profile, -32768)
    stage(gis, "fill_depressions / D8 / accumulation", version=pyflwdir.__version__)
    filled, d8, flow, accumulation = flow_from_dem(dem, grid)
    write_raster(gis / "dem_filled.tif", filled, profile, -32768)
    write_raster(gis / "d8_pointer.tif", d8, profile, 247)
    write_raster(gis / "accumulation.tif", accumulation, profile, -9999)
    streams = accumulation * resolution**2 / 1e6 >= args.stream_area_km2
    write_raster(gis / "streams.tif", streams.astype("uint8"), profile)
    stage(gis, "streams / bounded outlet search", stream_area_km2=args.stream_area_km2)
    forward = Transformer.from_crs(4326, crs, always_xy=True)
    inverse = Transformer.from_crs(crs, 4326, always_xy=True)
    reference = geom_transform(forward.transform, boundary(args.raw))
    ref_mask = geometry_mask([mapping(reference)], (height, width), grid, invert=True)
    stations = pd.read_excel(args.raw / "ST_STNM.xlsx")
    outlet = stations.loc[stations["站名"].astype(str) == args.outlet_station]
    if len(outlet) != 1:
        raise ValueError("Exactly one named outlet station required")
    lon, lat = float(outlet.iloc[0]["经度"]), float(outlet.iloc[0]["纬度"])
    table_location = [lon, lat]
    gis_location = None
    with fiona.open(args.raw / "GIS图层" / "流域站网.shp", encoding="latin1") as src:
        for feature in src:
            props = {k.encode("latin1").decode("utf-8", errors="replace"): v for k, v in feature["properties"].items()}
            if str(props.get("站码")) == str(outlet.iloc[0]["站码"]):
                gis_location = list(feature["geometry"]["coordinates"])
    if args.outlet_coordinate_source == "gis":
        if gis_location is None:
            raise ValueError("Outlet station code not found in GIS point layer")
        lon, lat = gis_location
    sx, sy = forward.transform(lon, lat)
    rows, cols = np.indices(dem.shape)
    xs = grid.c + (cols+.5)*resolution
    ys = grid.f - (rows+.5)*resolution
    distance = np.hypot(xs-sx, ys-sy)
    candidates = (distance <= args.snap_distance_m) & ref_mask
    if not candidates.any():
        raise ValueError("Outlet search radius does not intersect reference basin")
    # Explicit, bounded max-accumulation snap; record movement and compare basin.
    flat_index = np.argmax(np.where(candidates, accumulation, -np.inf))
    rr, cc = np.unravel_index(flat_index, dem.shape)
    pours = np.zeros(dem.shape, dtype="int32")
    pours[rr, cc] = 1
    write_raster(gis / "outlet.tif", pours, profile)
    stage(gis, "basins / subbasins_area", unit_area_km2=args.unit_area_km2)
    basin, labels, unit_outlets, local_flow = partition_catchment(
        d8, flow, flat_index, grid, args.unit_area_km2)
    write_raster(gis / "catchment.tif", basin.astype("int32"), profile)
    intersection = int(np.count_nonzero(basin & ref_mask))
    union = int(np.count_nonzero(basin | ref_mask))
    check = dict(outlet_station=args.outlet_station, original_wgs84=[lon, lat],
        coordinate_source=args.outlet_coordinate_source, station_table_wgs84=table_location,
        station_gis_wgs84=gis_location,
        snapped_wgs84=list(inverse.transform(xs[rr, cc], ys[rr, cc])), snap_distance_m=float(distance[rr, cc]),
        search_radius_m=args.snap_distance_m, dem_area_km2=float(basin.sum()*resolution**2/1e6),
        reference_area_km2=float(reference.area/1e6), intersection_over_union=intersection/union,
        touches_dem_edge=bool(basin[0].any() or basin[-1].any() or basin[:,0].any() or basin[:,-1].any()),
        accepted=False, human_review_required=True,
        note="Numerical acceptance is not confirmation of the true gauge catchment. Inspect outlet, reference boundary, and conflicting station coordinates.")
    dump(gis / "boundary_check.json", check)
    if check["touches_dem_edge"] or check["intersection_over_union"] < args.min_iou:
        raise ValueError(f"Outlet/catchment needs manual review: {check}; no model inputs built")
    check["accepted"] = True
    dump(gis / "boundary_check.json", check)
    old_ids = np.unique(labels[basin])
    if len(old_ids) < 2 and getattr(args, "model_mode", "distributed") != "lumped":
        raise ValueError("Only one unit; reduce --unit-area-km2")
    units = np.zeros(dem.shape, dtype="int32")
    records = []
    for uid, old in enumerate(old_ids, 1):
        mask = basin & (labels == old)
        units[mask] = uid
        records.append(dict(unit_id=uid, source_basin_id=int(old), cells=int(mask.sum()),
                            area_km2=float(mask.sum()*resolution**2/1e6), mean_elevation_m=float(dem[mask].mean())))
    write_raster(gis / "units.tif", units, profile)
    pd.DataFrame(records).to_csv(gis / "units.csv", index=False)
    network = []
    for idx in unit_outlets:
        uid = int(units.flat[idx])
        downstream_idx = int(local_flow.idxs_ds[idx])
        downstream_uid = int(units.flat[downstream_idx]) if downstream_idx != idx else 0
        if downstream_uid == uid:
            raise ValueError("Unit outlet must flow to a different unit or terminate")
        network.append(dict(unit_id=uid, downstream_unit_id=downstream_uid,
                            outlet_index=int(idx), outlet_wgs84=list(inverse.transform(xs.flat[idx], ys.flat[idx]))))
    dump(gis / "unit_topology.json", network)
    river_features = flow.streams(mask=streams & basin)
    for feature in river_features:
        feature["geometry"] = mapping(geom_transform(inverse.transform, shape(feature["geometry"])))
        feature["properties"] = {key: value.item() if isinstance(value, np.generic) else value
                                 for key, value in feature["properties"].items()}
    dump(gis / "streams.geojson", dict(type="FeatureCollection", features=river_features))
    features = []
    for geometry, value in shapes(units, mask=basin, transform=grid):
        geometry = geom_transform(inverse.transform, shape(geometry))
        features.append(dict(type="Feature", properties={"unit_id": int(value)}, geometry=mapping(geometry)))
    dump(gis / "units.geojson", dict(type="FeatureCollection", features=features))
    dump(gis / "reference_boundary.geojson", dict(type="FeatureCollection", features=[dict(
        type="Feature", properties={}, geometry=mapping(boundary(args.raw)))]))
    # Save source payloads with the case, so the directory is independently reviewable.
    source_dir = case / "source_dem"
    source_dir.mkdir()
    shutil.copy2(args.dem / "sources.json", source_dir / "sources.json")
    for record in sources["tiles"]:
        shutil.copy2(args.dem / record["file"], source_dir / record["file"])
    dump(case / "dem_config.json", dict(resolution_m=resolution, crs=crs,
        model_mode="distributed",
        stream_area_km2=args.stream_area_km2, unit_area_km2=args.unit_area_km2,
        min_iou=args.min_iou, boundary_check=check,
        unit_count=len(records), backend="pyflwdir", backend_version=pyflwdir.__version__,
        d8_encoding="ESRI / PyFlwDir: pit=0, nodata=247; incompatible with Whitebox pointer values",
        partition_method="subbasins_area within selected gauge catchment; threshold is km2, not fixed unit count",
        routing="Each disjoint unit independently routed to the common outlet by native xaj.Model; not a river-network cascade."))
    if getattr(args, "model_mode", "distributed") == "lumped":
        merge_units(case)
    dump(gis / "map_layers.json", render_map(case, args.raw))
    actual_units = 1 if getattr(args, "model_mode", "distributed") == "lumped" else len(records)
    print(f"Delineated {actual_units} model unit(s), {check['dem_area_km2']:.2f} km², IoU={check['intersection_over_union']:.3f}: {case}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["download", "delineate", "build"])
    parser.add_argument("--model-mode", choices=["distributed", "lumped"], default="distributed")
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--dem", type=Path, default=DEM)
    parser.add_argument("--case-dir", type=Path, default=ROOT / "case" / "pyflwdir-distributed-yaogu")
    parser.add_argument("--resolution", type=float, default=90)
    parser.add_argument("--stream-area-km2", type=float, default=100)
    parser.add_argument("--unit-area-km2", type=float, default=100, help="PyFlwDir subbasins_area threshold (km²), independent of displayed stream threshold")
    parser.add_argument("--outlet-station", default="腰古")
    parser.add_argument("--outlet-coordinate-source", choices=["table", "gis"], default="table")
    parser.add_argument("--snap-distance-m", type=float, default=2000)
    parser.add_argument("--min-iou", type=float, default=.85)
    parser.add_argument("--prepare-only", action="store_true", help="Build inputs without running XAJ (human review gate)")
    args = parser.parse_args()
    if not (args.resolution > 0 and args.stream_area_km2 > 0 and args.unit_area_km2 > 0 and args.snap_distance_m > 0 and 0 < args.min_iou <= 1):
        parser.error("resolution, stream area, snap radius must be positive; 0 < min-iou <= 1")
    if args.command == "build":
        from distributed_xaj_lab import build
        build(args.raw, args.case_dir, run=not args.prepare_only)
    else:
        globals()[args.command](args)


if __name__ == "__main__":
    main()
