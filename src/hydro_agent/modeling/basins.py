"""US basin catalog and local materials registry (open-data + legacy CAMELS)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydro_agent.modeling.plans import write_json

# Builtin product catalog. Leaf River is the professor-recommended primary site.
BUILTIN_BASINS: tuple[dict[str, Any], ...] = (
    {
        "basin_id": "usgs_02472000",
        "usgs_site": "02472000",
        "label": "Leaf River near Collins (MS)",
        "region": "Mississippi, USA",
        "kind": "builtin",
        "adapter": "open-v1",
        "default_start": "2019-10-01",
        "default_end": "2020-03-31",
        "primary": True,
    },
    {
        "basin_id": "camels_13235000",
        "usgs_site": "13235000",
        "label": "Lowman · South Fork Payette (ID)",
        "region": "Idaho, USA",
        "kind": "builtin",
        "adapter": "multimet-legacy",
        "default_start": "2019-05-03",
        "default_end": "2020-05-04",
        "primary": False,
    },
    {
        "basin_id": "camels_01123000",
        "usgs_site": "01123000",
        "label": "Pendleton Hill · Housatonic (CT)",
        "region": "Connecticut, USA",
        "kind": "builtin",
        "adapter": "multimet-legacy",
        "default_start": "2019-05-03",
        "default_end": "2020-05-04",
        "primary": False,
    },
)


@dataclass
class MaterialsStatus:
    hydro: bool
    dem: bool
    gis: bool

    @property
    def ready_for_build(self) -> bool:
        return self.hydro

    @property
    def complete(self) -> bool:
        return self.hydro and self.dem and self.gis

    def as_dict(self) -> dict[str, bool]:
        return {"hydro": self.hydro, "dem": self.dem, "gis": self.gis}


class BasinCatalog:
    def __init__(self, root: Path, *, legacy_source: Path | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.legacy_source = Path(legacy_source).resolve() if legacy_source else None
        self._seed_builtin_metadata()
        self._link_legacy_lowman_if_present()

    def directory(self, basin_id: str) -> Path:
        if not (basin_id.startswith("camels_") or basin_id.startswith("usgs_")):
            raise ValueError("basin id must be camels_* or usgs_*")
        path = (self.root / basin_id).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("invalid basin id")
        return path

    def _meta_path(self, basin_id: str) -> Path:
        return self.directory(basin_id) / "catalog.json"

    def _seed_builtin_metadata(self) -> None:
        for entry in BUILTIN_BASINS:
            basin_id = entry["basin_id"]
            folder = self.directory(basin_id)
            folder.mkdir(parents=True, exist_ok=True)
            meta_path = self._meta_path(basin_id)
            if meta_path.is_file():
                # Refresh label/adapter fields without wiping user status.
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
                for key in ("label", "region", "adapter", "usgs_site", "primary", "default_start", "default_end"):
                    if key in entry:
                        existing[key] = entry[key]
                write_json(meta_path, existing)
                continue
            write_json(
                meta_path,
                {
                    **entry,
                    "status": "registered",
                    "missing": ["hydro", "dem", "gis"],
                },
            )

    def _link_legacy_lowman_if_present(self) -> None:
        if self.legacy_source is None:
            return
        src = self.legacy_source / "camels_13235000"
        if not (src / "forcing.jsonl").is_file():
            return
        hydro = self.directory("camels_13235000") / "hydro"
        if (hydro / "forcing.jsonl").is_file():
            return
        hydro.mkdir(parents=True, exist_ok=True)
        for name in ("forcing.jsonl", "flow.jsonl", "basin.json", "source-manifest.json"):
            path = src / name
            if path.is_file():
                shutil.copy2(path, hydro / name)
        basin_path = hydro / "basin.json"
        if basin_path.is_file():
            basin = json.loads(basin_path.read_text(encoding="utf-8"))
            basin.setdefault("latitude", 44.0838)
            basin.setdefault("longitude", -115.6215)
            basin.setdefault("usgs_site", "13235000")
            write_json(basin_path, basin)
            write_json(
                hydro / "outlet.json",
                dict(
                    latitude=basin["latitude"],
                    longitude=basin["longitude"],
                    area_km2=basin["area_km2"],
                    usgs_site="13235000",
                ),
            )
        self._refresh_catalog_status("camels_13235000")

    def materials(self, basin_id: str) -> MaterialsStatus:
        root = self.directory(basin_id)
        hydro = (root / "hydro" / "forcing.jsonl").is_file() and (root / "hydro" / "flow.jsonl").is_file()
        dem = (root / "dem" / "sources.json").is_file() or any((root / "dem").glob("*.hgt"))
        gis = (root / "gis" / "boundary.geojson").is_file() or (root / "gis" / "outlet.geojson").is_file()
        return MaterialsStatus(hydro=hydro, dem=dem, gis=gis)

    def _refresh_catalog_status(self, basin_id: str) -> dict[str, Any]:
        meta = self.get(basin_id)
        mats = self.materials(basin_id)
        missing = [k for k, ok in mats.as_dict().items() if not ok]
        meta["materials"] = mats.as_dict()
        meta["missing"] = missing
        meta["ready_for_build"] = mats.ready_for_build
        meta["complete"] = mats.complete
        meta["status"] = "complete" if mats.complete else ("partial" if mats.hydro else "registered")
        write_json(self._meta_path(basin_id), meta)
        return meta

    def get(self, basin_id: str) -> dict[str, Any]:
        path = self._meta_path(basin_id)
        if not path.is_file():
            builtin = next((b for b in BUILTIN_BASINS if b["basin_id"] == basin_id), None)
            if builtin is None and not self.directory(basin_id).exists():
                raise KeyError(basin_id)
            self.directory(basin_id).mkdir(parents=True, exist_ok=True)
            write_json(
                path,
                {
                    **(builtin or {"basin_id": basin_id, "label": basin_id, "kind": "downloaded"}),
                    "status": "registered",
                },
            )
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict[str, Any]]:
        ids = {b["basin_id"] for b in BUILTIN_BASINS}
        for path in self.root.glob("*/catalog.json"):
            ids.add(path.parent.name)
        rows = [self._refresh_catalog_status(basin_id) for basin_id in sorted(ids)]
        rows.sort(key=lambda r: (not r.get("primary", False), r["basin_id"]))
        return rows

    def require_buildable(self, basin_id: str) -> dict[str, Any]:
        meta = self._refresh_catalog_status(basin_id)
        if not meta.get("ready_for_build"):
            raise ValueError(f"流域资料不足，请先下载：{basin_id}")
        return meta

    def hydro_dir(self, basin_id: str) -> Path:
        return self.directory(basin_id) / "hydro"

    def dem_dir(self, basin_id: str) -> Path:
        return self.directory(basin_id) / "dem"

    def gis_dir(self, basin_id: str) -> Path:
        return self.directory(basin_id) / "gis"
