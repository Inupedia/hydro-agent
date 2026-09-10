"""Spatial discretization for lumped and distributed hydrologic model plans.

Distributed mode deliberately has no synthetic/equal-area fallback. It uses the
open-source pyflwdir hydrology algorithms already carried by the ``xaj-dem`` extra.
If DEM/GIS inputs or the optional spatial dependencies are missing, model preparation
fails explicitly instead of publishing a fake distributed plan.
"""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpatialBuildResult:
    units: tuple[dict[str, object], ...]
    spatial_method: str
    streams_file: str | None = None
    units_geojson_file: str | None = None


def build_lumped_units(*, area_km2: float) -> SpatialBuildResult:
    return SpatialBuildResult(
        units=(
            {
                "unit_id": 1,
                "area_km2": float(area_km2),
                "source": "full-basin",
                "centroid_lon": None,
                "centroid_lat": None,
            },
        ),
        spatial_method="full-basin",
    )


def _load_spatial_dependencies():
    try:
        import numpy as np
        import pyflwdir
        import rasterio
        from pyproj import Geod
        from rasterio.features import shapes
        from rasterio.mask import mask as raster_mask
        from rasterio.merge import merge
        from shapely.geometry import mapping, shape
        from shapely.ops import unary_union
    except ImportError as exc:  # pragma: no cover - exercised by integration env
        raise RuntimeError(
            "distributed 模式需要 xaj-dem 依赖（pyflwdir/rasterio/shapely/pyproj）；"
            "不允许回退为等面积伪分布式"
        ) from exc
    return np, pyflwdir, rasterio, Geod, shapes, raster_mask, merge, mapping, shape, unary_union


def _read_boundary(gis_dir: Path) -> dict:
    path = gis_dir / "boundary.geojson"
    if not path.is_file():
        raise ValueError("distributed 模式缺少真实流域 boundary.geojson")
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") or []
    if not features:
        raise ValueError("distributed 模式的流域边界为空")
    if any(bool((f.get("properties") or {}).get("approximation")) for f in features):
        raise ValueError("distributed 模式禁止使用近似圆形边界，请获取真实流域边界")
    return payload


def build_pyflwdir_units(
    *,
    dem_dir: Path,
    gis_dir: Path,
    output_dir: Path,
    unit_area_km2: float,
    stream_area_km2: float,
    max_units: int = 32,
) -> SpatialBuildResult:
    (
        np,
        pyflwdir,
        rasterio,
        Geod,
        raster_shapes,
        raster_mask,
        raster_merge,
        mapping,
        shape,
        unary_union,
    ) = _load_spatial_dependencies()

    boundary = _read_boundary(gis_dir)
    hgt_files = sorted(Path(dem_dir).glob("*.hgt"))
    if not hgt_files:
        raise ValueError("distributed 模式缺少 SRTM HGT DEM，请先下载地形资料")
    output_dir.mkdir(parents=True, exist_ok=True)
    mosaic_path = output_dir / "dem-mosaic.tif"

    sources = [rasterio.open(path) for path in hgt_files]
    try:
        mosaic, transform = raster_merge(sources)
        profile = sources[0].profile.copy()
        profile.update(
            driver="GTiff",
            height=mosaic.shape[1],
            width=mosaic.shape[2],
            transform=transform,
            count=1,
            nodata=-32768,
        )
        with rasterio.open(mosaic_path, "w", **profile) as dst:
            dst.write(mosaic[0], 1)
    finally:
        for src in sources:
            src.close()

    geometries = [feature["geometry"] for feature in boundary.get("features") or []]
    with rasterio.open(mosaic_path) as src:
        dem, clipped_transform = raster_mask(
            src,
            geometries,
            crop=True,
            nodata=-32768,
            filled=True,
        )
        elevation = dem[0].astype("float64")
        crs = src.crs
    if crs is None:
        raise ValueError("DEM 缺少坐标参考系")
    valid = elevation != -32768
    if not np.any(valid):
        raise ValueError("流域边界与 DEM 没有有效交集")

    flw = pyflwdir.from_dem(
        data=elevation,
        nodata=-32768,
        transform=clipped_transform,
        latlon=bool(crs.is_geographic),
    )
    upstream_area = flw.upstream_area(unit="km2")
    subbasins, outlet_idxs = flw.subbasins_area(
        area_min=float(unit_area_km2),
        uparea=upstream_area,
    )
    ids = sorted(int(v) for v in np.unique(subbasins) if int(v) > 0)
    if len(ids) < 2:
        raise ValueError(
            "自动分区仅生成 1 个计算单元；请降低单元面积阈值或改用集总式模型"
        )
    if len(ids) > max_units:
        raise ValueError(
            f"自动分区生成 {len(ids)} 个单元，超过产品上限 {max_units}；"
            "请提高单元面积阈值"
        )

    geod = Geod(ellps="WGS84")
    unit_features: list[dict[str, object]] = []
    units: list[dict[str, object]] = []
    for unit_id in ids:
        pieces = [
            shape(geom)
            for geom, value in raster_shapes(
                subbasins.astype("int32"),
                mask=subbasins == unit_id,
                transform=clipped_transform,
            )
            if int(value) == unit_id
        ]
        if not pieces:
            continue
        geometry = unary_union(pieces)
        area_m2 = abs(float(geod.geometry_area_perimeter(geometry)[0]))
        area_km2 = area_m2 / 1_000_000.0
        centroid = geometry.representative_point()
        props = {
            "unit_id": unit_id,
            "area_km2": area_km2,
            "source": "pyflwdir-subbasins-area",
            "centroid_lon": float(centroid.x),
            "centroid_lat": float(centroid.y),
        }
        unit_features.append(
            {"type": "Feature", "properties": props, "geometry": mapping(geometry)}
        )
        units.append(props)

    if len(units) < 2:
        raise ValueError("DEM 分区未形成至少两个有效计算单元")

    units_geojson = output_dir / "units.geojson"
    units_geojson.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": unit_features},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with (output_dir / "units.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "unit_id",
                "area_km2",
                "source",
                "centroid_lon",
                "centroid_lat",
            ],
        )
        writer.writeheader()
        writer.writerows(units)

    stream_mask = upstream_area >= float(stream_area_km2)
    stream_order = flw.stream_order(type="strahler", mask=stream_mask)
    stream_features = flw.streams(mask=stream_mask, strord=stream_order, uparea=upstream_area)
    streams_geojson = output_dir / "streams.geojson"
    streams_geojson.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": stream_features},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    outlet_xy = flw.xy(outlet_idxs)
    outlets = [
        {
            "type": "Feature",
            "properties": {"unit_id": int(unit_id)},
            "geometry": {"type": "Point", "coordinates": [float(x), float(y)]},
        }
        for unit_id, x, y in zip(ids, outlet_xy[0], outlet_xy[1], strict=False)
    ]
    (output_dir / "unit-outlets.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": outlets}, ensure_ascii=False),
        encoding="utf-8",
    )

    mosaic_path.unlink(missing_ok=True)
    return SpatialBuildResult(
        units=tuple(units),
        spatial_method="pyflwdir-subbasins-area",
        streams_file=str(streams_geojson.name),
        units_geojson_file=str(units_geojson.name),
    )


def copy_lumped_review_inputs(*, source_gis_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "boundary.geojson",
        "outlet.geojson",
        "bbox.json",
        "boundary_check.json",
        "nldi_feature.json",
        "flowlines.geojson",
        "streams.geojson",
    ):
        source = source_gis_dir / name
        if source.is_file():
            shutil.copy2(source, output_dir / name)
