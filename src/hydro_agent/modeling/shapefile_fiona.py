"""Minimal fiona.open() stand-in for teacher dem_xaj_lab.py.

Fiona has no linux/arm64 wheel. The academy case only needs to read Point,
PolyLine and Polygon shapefiles; this parser uses the standard library.
Copied into each plan builder directory as fiona.py so the vendor script
stays byte-identical.
"""
from __future__ import annotations

import struct
from pathlib import Path

__version__ = "0.1.0-shapefile-shim"

_NULL, _POINT, _POLYLINE, _POLYGON = 0, 1, 3, 5


def _closed(ring: list[list[float]]) -> list[list[float]]:
    if ring and ring[0] != ring[-1]:
        return ring + [ring[0]]
    return ring


def _geometry(shape_type: int, body: bytes) -> dict | None:
    if shape_type == _NULL:
        return None
    if shape_type == _POINT:
        x, y = struct.unpack_from("<dd", body)
        return {"type": "Point", "coordinates": [x, y]}
    if shape_type not in {_POLYLINE, _POLYGON}:
        raise ValueError(f"unsupported shapefile type {shape_type}")
    nparts, npts = struct.unpack_from("<ii", body, 32)
    parts = struct.unpack_from(f"<{nparts}i", body, 40)
    xy_off = 40 + 4 * nparts
    xy = struct.unpack_from(f"<{npts * 2}d", body, xy_off)
    points = [[xy[i], xy[i + 1]] for i in range(0, len(xy), 2)]
    starts = list(parts) + [npts]
    rings = [_closed(points[a:b]) for a, b in zip(starts, starts[1:])]
    if shape_type == _POLYLINE:
        if len(rings) == 1:
            return {"type": "LineString", "coordinates": rings[0]}
        return {"type": "MultiLineString", "coordinates": rings}
    return {"type": "Polygon", "coordinates": rings}


def _field_name(raw: bytes, encoding: str) -> str:
    return raw.split(b"\x00", 1)[0].decode(encoding, errors="replace")


def _parse_dbf(path: Path, encoding: str) -> tuple[list[str], list[dict]]:
    payload = path.read_bytes()
    rec_count, header_len, rec_len = struct.unpack_from("<IHH", payload, 4)
    names: list[str] = []
    specs: list[tuple[str, int, int]] = []
    offset = 32
    while offset < header_len - 1 and payload[offset] != 0x0D:
        chunk = payload[offset : offset + 32]
        names.append(_field_name(chunk[:11], encoding))
        specs.append((chr(chunk[11]), chunk[16], chunk[17]))
        offset += 32
    rows = []
    cursor = header_len
    for _ in range(rec_count):
        record = payload[cursor : cursor + rec_len]
        cursor += rec_len
        if not record or record[:1] == b"*":
            continue
        values = {}
        pos = 1
        for name, (kind, length, decimals) in zip(names, specs):
            raw = record[pos : pos + length]
            pos += length
            text = raw.decode(encoding, errors="replace").strip().strip("\x00")
            if kind in {"N", "F"} and text:
                values[name] = float(text) if decimals or "." in text else int(text)
            elif kind == "L":
                values[name] = text[:1] in {"T", "t", "Y", "y"}
            else:
                values[name] = text
        rows.append(values)
    return names, rows


class Collection:
    def __init__(self, path, encoding: str = "utf-8"):
        self.path = Path(path)
        prj = self.path.with_suffix(".prj")
        self.crs = prj.read_text(encoding="ascii", errors="replace").strip() if prj.is_file() else None
        geometries = self._shapes()
        _, rows = _parse_dbf(self.path.with_suffix(".dbf"), encoding)
        if len(rows) != len(geometries):
            raise ValueError(f"shapefile/dbf record count mismatch: {self.path}")
        self._features = [
            {"type": "Feature", "id": str(i), "properties": props, "geometry": geom}
            for i, (geom, props) in enumerate(zip(geometries, rows))
        ]

    def _shapes(self) -> list[dict | None]:
        payload = self.path.read_bytes()
        if len(payload) < 100 or struct.unpack_from(">i", payload)[0] != 9994:
            raise ValueError(f"not a shapefile: {self.path}")
        out = []
        offset = 100
        while offset + 8 <= len(payload):
            _recno, words = struct.unpack_from(">ii", payload, offset)
            size = 8 + words * 2
            body = payload[offset + 8 : offset + size]
            shape_type = struct.unpack_from("<i", body)[0]
            out.append(_geometry(shape_type, body[4:]))
            offset += size
        return out

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __iter__(self):
        return iter(self._features)

    def __len__(self):
        return len(self._features)


def open(path, mode: str = "r", encoding: str = "utf-8", **_kwargs):
    if mode not in {"r", "rb"}:
        raise ValueError("shapefile shim is read-only")
    return Collection(path, encoding=encoding)
