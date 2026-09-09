"""Render a simple basin review map (SVG) for boundary confirmation."""

from __future__ import annotations

import json
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
    return []


def _bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def render_basin_review_map(gis_dir: Path, *, title: str = "Basin review") -> Path:
    """Write ``units_map.svg`` from boundary/outlet GeoJSON. Returns the SVG path."""
    gis_dir = Path(gis_dir)
    gis_dir.mkdir(parents=True, exist_ok=True)
    boundary_path = gis_dir / "boundary.geojson"
    outlet_path = gis_dir / "outlet.geojson"
    if not boundary_path.is_file():
        raise FileNotFoundError("boundary.geojson missing")

    boundary = json.loads(boundary_path.read_text(encoding="utf-8"))
    features = boundary.get("features") or ([boundary] if boundary.get("geometry") else [])
    rings: list[list[tuple[float, float]]] = []
    for feature in features:
        geom = feature.get("geometry") or feature
        rings.extend(_rings(geom))
    if not rings:
        raise ValueError("boundary geometry empty")

    outlet_xy: tuple[float, float] | None = None
    if outlet_path.is_file():
        outlet = json.loads(outlet_path.read_text(encoding="utf-8"))
        for feature in outlet.get("features") or []:
            geom = feature.get("geometry") or {}
            if geom.get("type") == "Point":
                outlet_xy = (float(geom["coordinates"][0]), float(geom["coordinates"][1]))
                break

    all_pts = [p for ring in rings for p in ring]
    if outlet_xy:
        all_pts.append(outlet_xy)
    west, south, east, north = _bbox(all_pts)
    pad_x = max((east - west) * 0.08, 0.01)
    pad_y = max((north - south) * 0.08, 0.01)
    west, south, east, north = west - pad_x, south - pad_y, east + pad_x, north + pad_y
    width, height = 900.0, 720.0

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = (lon - west) / max(east - west, 1e-9) * width
        y = (1.0 - (lat - south) / max(north - south, 1e-9)) * height
        return x, y

    paths = []
    for ring in rings:
        if len(ring) < 2:
            continue
        parts = [f"{'M' if i == 0 else 'L'}{project(x, y)[0]:.2f},{project(x, y)[1]:.2f}" for i, (x, y) in enumerate(ring)]
        paths.append(" ".join(parts) + " Z")

    outlet_mark = ""
    if outlet_xy:
        ox, oy = project(*outlet_xy)
        outlet_mark = (
            f'<circle cx="{ox:.2f}" cy="{oy:.2f}" r="8" fill="#007AFF" stroke="#FFFFFF" stroke-width="2.5"/>'
            f'<circle cx="{ox:.2f}" cy="{oy:.2f}" r="3" fill="#FFFFFF"/>'
            f'<text x="{ox + 12:.2f}" y="{oy - 10:.2f}" fill="#1D1D1F" font-size="14" '
            f'font-family="-apple-system,BlinkMacSystemFont,sans-serif">outlet</text>'
        )

    path_xml = "\n".join(
        f'<path d="{d}" fill="rgba(0,122,255,0.12)" stroke="#007AFF" stroke-width="2.2" '
        f'stroke-linejoin="round"/>'
        for d in paths
    )
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" role="img">
  <rect width="100%" height="100%" fill="#F5F5F7"/>
  <rect x="18" y="18" width="{width - 36:.0f}" height="{height - 36:.0f}" rx="18" fill="#FFFFFF" stroke="#E5E5EA"/>
  <text x="40" y="52" fill="#1D1D1F" font-size="20" font-weight="600"
        font-family="-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif">{title}</text>
  <text x="40" y="74" fill="#62626A" font-size="12"
        font-family="-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif">NLDI basin boundary · USGS outlet</text>
  <g transform="translate(0,12)">
    {path_xml}
    {outlet_mark}
  </g>
</svg>
"""
    out = gis_dir / "units_map.svg"
    out.write_text(svg, encoding="utf-8")
    return out
