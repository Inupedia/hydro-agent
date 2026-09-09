"""Render a basin review map (SVG): boundary, units, rivers, outlet."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any


def _rings(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        return [[(float(x), float(y)) for x, y in ring] for ring in coords]
    if gtype == "MultiPolygon":
        out: list[list[tuple[float, float]]] = []
        for poly in coords:
            for ring in poly:
                out.append([(float(x), float(y)) for x, y in ring])
        return out
    if gtype == "Point":
        return [[(float(coords[0]), float(coords[1]))]]
    if gtype == "LineString":
        return [[(float(x), float(y)) for x, y in coords]]
    if gtype == "MultiLineString":
        return [[(float(x), float(y)) for x, y in line] for line in coords]
    return []


def _bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _centroid(ring: list[tuple[float, float]]) -> tuple[float, float]:
    if len(ring) < 3:
        return ring[0] if ring else (0.0, 0.0)
    # Exclude duplicate closing vertex when present.
    pts = ring[:-1] if ring[0] == ring[-1] else ring
    area = 0.0
    cx = 0.0
    cy = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        cross = x1 * y2 - x2 * y1
        area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(area) < 1e-18:
        return (
            sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts),
        )
    area *= 0.5
    return cx / (6.0 * area), cy / (6.0 * area)


def _load_feature_rings(path: Path) -> list[list[tuple[float, float]]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") or ([payload] if payload.get("geometry") else [])
    rings: list[list[tuple[float, float]]] = []
    for feature in features:
        geom = feature.get("geometry") or feature
        rings.extend(_rings(geom))
    return rings


def _sector_polygons(
    outer: list[tuple[float, float]],
    *,
    unit_count: int,
    outlet: tuple[float, float] | None,
) -> list[tuple[int, list[tuple[float, float]]]]:
    """Approximate equal-angle unit wedges from outlet/centroid for review drawing."""
    if unit_count <= 1 or len(outer) < 3:
        return [(1, outer)]
    origin = outlet or _centroid(outer)
    # Sample boundary angles relative to origin.
    pts = outer[:-1] if outer[0] == outer[-1] else outer
    angled = []
    for x, y in pts:
        angled.append((math.atan2(y - origin[1], x - origin[0]), (x, y)))
    angled.sort(key=lambda item: item[0])
    if not angled:
        return [(1, outer)]
    # Walk full circle into N wedges; pick boundary points whose angle falls in wedge.
    wedges: list[tuple[int, list[tuple[float, float]]]] = []
    step = 2.0 * math.pi / unit_count
    start_angle = angled[0][0]
    for i in range(unit_count):
        a0 = start_angle + i * step
        a1 = start_angle + (i + 1) * step
        sector = [origin]
        for ang, pt in angled:
            # Normalize into [a0, a0+2π)
            rel = ang
            while rel < a0:
                rel += 2.0 * math.pi
            while rel >= a0 + 2.0 * math.pi:
                rel -= 2.0 * math.pi
            if a0 <= rel <= a1 + 1e-9:
                sector.append(pt)
        # Ray endpoints at a0/a1 using mean radius.
        radii = [math.hypot(pt[0] - origin[0], pt[1] - origin[1]) for _, pt in angled]
        radius = sorted(radii)[len(radii) // 2] if radii else 0.01
        for ang in (a0, a1):
            sector.append((origin[0] + radius * math.cos(ang), origin[1] + radius * math.sin(ang)))
        if len(sector) >= 3:
            sector.append(sector[0])
            wedges.append((i + 1, sector))
    return wedges or [(1, outer)]


def write_units_geojson(
    gis_dir: Path,
    *,
    unit_count: int,
    outlet_xy: tuple[float, float] | None = None,
) -> Path | None:
    """Persist approximate unit polygons for distributed review maps."""
    gis_dir = Path(gis_dir)
    boundary_rings = _load_feature_rings(gis_dir / "boundary.geojson")
    if not boundary_rings:
        return None
    outer = max(boundary_rings, key=len)
    sectors = _sector_polygons(outer, unit_count=unit_count, outlet=outlet_xy)
    colors = ["#5AC8FA", "#007AFF", "#5856D6", "#AF52DE", "#FF2D55", "#FF9500", "#34C759", "#8E8E93"]
    features = []
    for unit_id, ring in sectors:
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "unit_id": unit_id,
                    "label": f"U{unit_id}",
                    "color": colors[(unit_id - 1) % len(colors)],
                },
                "geometry": {"type": "Polygon", "coordinates": [[[x, y] for x, y in ring]]},
            }
        )
    out = gis_dir / "units.geojson"
    out.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    return out


def render_basin_review_map(gis_dir: Path, *, title: str = "Basin review") -> Path:
    """Write ``units_map.svg`` with boundary, unit wedges, rivers, and outlet."""
    gis_dir = Path(gis_dir)
    gis_dir.mkdir(parents=True, exist_ok=True)
    boundary_path = gis_dir / "boundary.geojson"
    if not boundary_path.is_file():
        raise FileNotFoundError("boundary.geojson missing")

    boundary_rings = _load_feature_rings(boundary_path)
    if not boundary_rings:
        raise ValueError("boundary geometry empty")

    outlet_xy: tuple[float, float] | None = None
    outlet_path = gis_dir / "outlet.geojson"
    if outlet_path.is_file():
        for ring in _load_feature_rings(outlet_path):
            if ring:
                outlet_xy = ring[0]
                break

    unit_count = 1
    units_csv = gis_dir / "units.csv"
    if units_csv.is_file():
        with units_csv.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        unit_count = max(len(rows), 1)

    if not (gis_dir / "units.geojson").is_file():
        write_units_geojson(gis_dir, unit_count=unit_count, outlet_xy=outlet_xy)

    unit_features: list[dict[str, Any]] = []
    units_path = gis_dir / "units.geojson"
    if units_path.is_file():
        unit_features = json.loads(units_path.read_text(encoding="utf-8")).get("features") or []

    river_rings: list[list[tuple[float, float]]] = []
    for name in ("flowlines.geojson", "streams.geojson"):
        river_rings.extend(_load_feature_rings(gis_dir / name))

    all_pts = [p for ring in boundary_rings for p in ring]
    if outlet_xy:
        all_pts.append(outlet_xy)
    for ring in river_rings:
        all_pts.extend(ring)
    for feature in unit_features:
        for ring in _rings(feature.get("geometry") or {}):
            all_pts.extend(ring)
    west, south, east, north = _bbox(all_pts)
    pad_x = max((east - west) * 0.08, 0.01)
    pad_y = max((north - south) * 0.08, 0.01)
    west, south, east, north = west - pad_x, south - pad_y, east + pad_x, north + pad_y
    width, height = 900.0, 720.0

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = (lon - west) / max(east - west, 1e-9) * width
        y = (1.0 - (lat - south) / max(north - south, 1e-9)) * height
        return x, y

    def path_d(ring: list[tuple[float, float]], *, closed: bool) -> str:
        parts = [
            f"{'M' if i == 0 else 'L'}{project(x, y)[0]:.2f},{project(x, y)[1]:.2f}"
            for i, (x, y) in enumerate(ring)
        ]
        d = " ".join(parts)
        return d + (" Z" if closed else "")

    unit_xml = []
    for feature in unit_features:
        props = feature.get("properties") or {}
        color = str(props.get("color") or "#5AC8FA")
        label = str(props.get("label") or props.get("unit_id") or "")
        for ring in _rings(feature.get("geometry") or {}):
            if len(ring) < 3:
                continue
            unit_xml.append(
                f'<path d="{path_d(ring, closed=True)}" fill="{color}" fill-opacity="0.18" '
                f'stroke="{color}" stroke-width="1.6" stroke-linejoin="round"/>'
            )
            cx, cy = project(*_centroid(ring))
            if label:
                unit_xml.append(
                    f'<text x="{cx:.2f}" y="{cy:.2f}" text-anchor="middle" dominant-baseline="middle" '
                    f'fill="#1D1D1F" font-size="13" font-weight="600" '
                    f'font-family="-apple-system,BlinkMacSystemFont,\'PingFang SC\',sans-serif">{label}</text>'
                )

    boundary_xml = []
    for ring in boundary_rings:
        if len(ring) < 2:
            continue
        boundary_xml.append(
            f'<path d="{path_d(ring, closed=True)}" fill="none" stroke="#1D1D1F" '
            f'stroke-width="2.4" stroke-linejoin="round"/>'
        )

    river_xml = []
    for ring in river_rings:
        if len(ring) < 2:
            continue
        # Thicker lines for longer reaches look like main channels.
        width_px = 1.4 if len(ring) < 12 else 2.2
        river_xml.append(
            f'<path d="{path_d(ring, closed=False)}" fill="none" stroke="#0A84FF" '
            f'stroke-width="{width_px}" stroke-linecap="round" stroke-linejoin="round" opacity="0.92"/>'
        )

    outlet_mark = ""
    if outlet_xy:
        ox, oy = project(*outlet_xy)
        outlet_mark = (
            f'<circle cx="{ox:.2f}" cy="{oy:.2f}" r="8" fill="#FF3B30" stroke="#FFFFFF" stroke-width="2.5"/>'
            f'<circle cx="{ox:.2f}" cy="{oy:.2f}" r="3" fill="#FFFFFF"/>'
            f'<text x="{ox + 12:.2f}" y="{oy - 10:.2f}" fill="#1D1D1F" font-size="14" '
            f'font-family="-apple-system,BlinkMacSystemFont,sans-serif">出口</text>'
        )

    legend_bits = ["边界"]
    if unit_features:
        legend_bits.append(f"计算单元 ×{len(unit_features)}")
    if river_rings:
        legend_bits.append(f"河网 {len(river_rings)} 段")
    if outlet_xy:
        legend_bits.append("出口")
    subtitle = " · ".join(legend_bits)

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" role="img">
  <rect width="100%" height="100%" fill="#F5F5F7"/>
  <rect x="18" y="18" width="{width - 36:.0f}" height="{height - 36:.0f}" rx="18" fill="#FFFFFF" stroke="#E5E5EA"/>
  <text x="40" y="52" fill="#1D1D1F" font-size="20" font-weight="600"
        font-family="-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif">{title}</text>
  <text x="40" y="74" fill="#62626A" font-size="12"
        font-family="-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif">{subtitle}</text>
  <g transform="translate(0,20)">
    {"".join(unit_xml)}
    {"".join(boundary_xml)}
    {"".join(river_xml)}
    {outlet_mark}
  </g>
</svg>
"""
    out = gis_dir / "units_map.svg"
    out.write_text(svg, encoding="utf-8")
    return out
