"""US CAMELS model-plan builder (lumped / distributed, notebook-aligned knobs)."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from hydro_agent.data.windows import recommended_task_window
from hydro_agent.modeling.basins import BasinCatalog
from hydro_agent.modeling.plans import digest, write_json
from hydro_agent.models.xaj.contracts import XajScheme
from hydro_agent.models.xaj.upstream import MODEL_SHA256, MODEL_VERSION

STAGES = (
    ("M00_ENSURE_MATERIALS", "检查并确认美国站资料"),
    ("M02_DELINEATE", "划分计算单元"),
    ("M03_REVIEW_BOUNDARY", "复核出口与流域边界"),
    ("M04_BUILD_INPUTS", "构建强迫与模型输入"),
    ("M05_VALIDATE_PLAN", "校验并保存完整方案"),
)

DEFAULT_PARAMS = {
    "K": 0.75,
    "B": 0.25,
    "IM": 0.06,
    "UM": 20.0,
    "LM": 60.0,
    "DM": 40.0,
    "C": 0.16,
    "SM": 20.0,
    "EX": 1.2,
    "KI": 0.3,
    "KG": 0.4,
    "CS": 0.9,
    "L": 2.0,
    "CI": 0.8,
    "CG": 0.98,
}


def _parse_csv_bool(value: object, *, default: bool = True) -> bool:
    """Parse quality booleans emitted by ``_build_inputs`` without changing meaning."""

    if value is None or str(value).strip() == "":
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"invalid boolean value in model-plan input: {value!r}")


class UsPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    basin_id: str = Field(default="usgs_02472000", min_length=3)
    model_mode: Literal["lumped", "distributed"] = "lumped"
    resolution_m: float = Field(default=90, ge=30, le=1000)
    stream_area_km2: float = Field(default=50, gt=0, le=10000)
    unit_area_km2: float = Field(default=50, gt=0, le=10000)
    warmup_days: int = Field(default=30, ge=1, le=1000)
    # Legacy API field; ignored. Unit count comes from pyflwdir subbasins_area.
    unit_count: int = Field(default=4, ge=2, le=32)
    snap_distance_m: float = Field(default=2000, gt=0, le=20000)
    min_iou: float = Field(default=0.7, gt=0, le=1)
    name: str | None = Field(default=None, max_length=80)


class UsModelPlanService:
    """Build forecast-ready plans from local US basin materials."""

    def __init__(self, root: Path, catalog: BasinCatalog):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog = catalog
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.RLock()
        for path in self.root.glob("plan-*/plan.json"):
            p = json.loads(path.read_text(encoding="utf-8"))
            if p.get("basin_id") == "yaogu":
                continue
            if p["status"] in ("running", "queued"):
                p.update(status="failed", error="服务重启中断了建模，请新建方案。")
                write_json(path, p)
            elif p.get("status") == "ready" and all(
                p.get(key) is not None for key in ("data_start", "data_end", "history_days")
            ):
                start, end = recommended_task_window(
                    date.fromisoformat(p["data_start"]),
                    date.fromisoformat(p["data_end"]),
                    int(p["history_days"]),
                )
                if date.fromisoformat(p.get("suggested_start") or p["data_start"]) < start:
                    p.update(suggested_start=str(start), suggested_end=str(end))
                    write_json(path, p)

    def directory(self, plan_id: str) -> Path:
        if not plan_id.startswith("plan-"):
            raise ValueError("invalid model plan id")
        return self.root / plan_id

    def get(self, plan_id: str) -> dict:
        path = self.directory(plan_id) / "plan.json"
        if not path.is_file():
            raise KeyError(plan_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        plans = [self.get(p.parent.name) for p in sorted(self.root.glob("plan-*/plan.json"), reverse=True)]
        return [plan for plan in plans if plan.get("basin_id") != "yaogu"]

    def delete(self, plan_id: str) -> None:
        with self.lock:
            plan = self.get(plan_id)
            if plan.get("status") in ("queued", "running"):
                raise ValueError("建模进行中，无法删除")
            shutil.rmtree(self.directory(plan_id))

    def _update(self, plan_id: str, **fields):
        with self.lock:
            plan = self.get(plan_id)
            plan.update(fields)
            write_json(self.directory(plan_id) / "plan.json", plan)
            return plan

    def _stage(self, plan_id: str, code: str, status: str, detail: str = ""):
        with self.lock:
            plan = self.get(plan_id)
            for stage in plan["stages"]:
                if stage["code"] == code:
                    stage.update(status=status, detail=detail)
            plan["current_stage"] = code
            write_json(self.directory(plan_id) / "plan.json", plan)

    def create(self, request: UsPlanRequest) -> dict:
        from hydro_agent.modeling.plans import normalize_display_name

        meta = self.catalog.require_buildable(request.basin_id)
        if request.model_mode == "distributed" and not meta.get("materials", {}).get("dem"):
            raise ValueError("distributed 模式需要先下载 DEM；请先完成地形下载")
        plan_id = f"plan-{uuid.uuid4().hex[:12]}"
        name = normalize_display_name(request.name)
        with self.lock:
            self.directory(plan_id).mkdir()
            payload = dict(
                plan_id=plan_id,
                basin_id=request.basin_id,
                model_mode=request.model_mode,
                status="queued",
                error=None,
                name=name,
                config=request.model_dump(exclude={"name"}),
                model_version=MODEL_VERSION,
                model_source_sha256=MODEL_SHA256,
                stages=[
                    dict(code=code, label=label, status="pending", detail="")
                    for code, label in STAGES
                ],
                boundary_reviewed=False,
            )
            write_json(self.directory(plan_id) / "plan.json", payload)
        self.pool.submit(self._build, plan_id, False)
        return payload

    def rename(self, plan_id: str, name: str | None) -> dict:
        from hydro_agent.modeling.plans import normalize_display_name

        return self._update(plan_id, name=normalize_display_name(name))

    def confirm(self, plan_id: str, boundary_hash: str) -> dict:
        with self.lock:
            p = self.get(plan_id)
            if p["status"] != "awaiting_review":
                raise ValueError("方案当前不在边界复核阶段")
            if boundary_hash != p.get("boundary_hash"):
                raise ValueError("边界版本已变化，请重新查看")
            self._stage(plan_id, "M03_REVIEW_BOUNDARY", "completed", "已确认出口与边界")
            self._update(plan_id, status="queued", boundary_reviewed=True)
            self.pool.submit(self._build, plan_id, True)
            return self.get(plan_id)

    def require_ready(self, plan_id: str) -> dict:
        p = self.get(plan_id)
        if p["status"] != "ready" or not p.get("boundary_reviewed"):
            raise ValueError("模型方案尚未完成建模、边界复核和输入校验")
        self._verify_files(plan_id, p["files"])
        return p

    def _verify_files(self, plan_id: str, files: dict):
        root = self.directory(plan_id)
        for relative, expected in files.items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or not path.is_file() or digest(path) != expected:
                raise ValueError(f"方案文件已变化或缺失：{relative}")

    def _build(self, plan_id: str, reviewed: bool) -> None:
        root = self.directory(plan_id)
        try:
            p = self._update(plan_id, status="running", error=None)
            cfg = UsPlanRequest.model_validate(p["config"])
            basin_id = cfg.basin_id
            hydro = self.catalog.hydro_dir(basin_id)
            if not reviewed:
                self._stage(plan_id, "M00_ENSURE_MATERIALS", "running")
                self.catalog.require_buildable(basin_id)
                self._stage(plan_id, "M00_ENSURE_MATERIALS", "completed", "水文资料齐备")
                self._stage(plan_id, "M02_DELINEATE", "running")
                case = root / "case"
                case.mkdir(exist_ok=True)
                gis = case / "gis"
                src_gis = self.catalog.gis_dir(basin_id)
                basin = json.loads((hydro / "basin.json").read_text(encoding="utf-8"))
                usgs_area = float(basin["area_km2"])

                if cfg.model_mode == "distributed":
                    from hydro_agent.modeling.us_delineate import delineate_open_basin

                    delineated = delineate_open_basin(
                        dem_dir=self.catalog.dem_dir(basin_id),
                        source_gis=src_gis,
                        case_dir=case,
                        resolution_m=cfg.resolution_m,
                        stream_area_km2=cfg.stream_area_km2,
                        unit_area_km2=cfg.unit_area_km2,
                        snap_distance_m=cfg.snap_distance_m,
                        min_iou=cfg.min_iou,
                        model_mode="distributed",
                    )
                    boundary = delineated["boundary_check"]
                    boundary["model_mode"] = "distributed"
                    boundary["unit_count"] = delineated["unit_count"]
                    boundary["usgs_area_km2"] = usgs_area
                    boundary.setdefault(
                        "forcing_note",
                        "gridMET gauge-point forcing applied uniformly to each DEM unit (V1)",
                    )
                    write_json(gis / "boundary_check.json", boundary)
                    area = float(delineated["area_km2"])
                    unit_count = int(delineated["unit_count"])
                    partition_method = delineated["dem_config"].get("partition_method")
                else:
                    if gis.exists():
                        shutil.rmtree(gis)
                    gis.mkdir(parents=True)
                    units = [dict(unit_id=1, area_km2=usgs_area, source="full-basin")]
                    with (gis / "units.csv").open("w", encoding="utf-8", newline="") as fh:
                        writer = csv.DictWriter(fh, fieldnames=["unit_id", "area_km2", "source"])
                        writer.writeheader()
                        writer.writerows(units)
                    for name in (
                        "boundary.geojson",
                        "outlet.geojson",
                        "bbox.json",
                        "boundary_check.json",
                        "nldi_feature.json",
                        "flowlines.geojson",
                        "streams.geojson",
                    ):
                        if (src_gis / name).is_file():
                            shutil.copy2(src_gis / name, gis / name)
                    if (gis / "boundary_check.json").is_file():
                        boundary = json.loads((gis / "boundary_check.json").read_text(encoding="utf-8"))
                        boundary["model_mode"] = "lumped"
                        boundary["unit_count"] = 1
                        boundary.setdefault(
                            "note",
                            "NLDI reference basin; gridMET gauge-point forcing; one XAJ",
                        )
                    else:
                        boundary = dict(
                            accepted=True,
                            dem_area_km2=usgs_area,
                            usgs_area_km2=usgs_area,
                            model_mode="lumped",
                            unit_count=1,
                            note="lumped: one XAJ for the full basin",
                        )
                    write_json(gis / "boundary_check.json", boundary)
                    write_json(
                        case / "dem_config.json",
                        dict(
                            resolution_m=cfg.resolution_m,
                            stream_area_km2=cfg.stream_area_km2,
                            unit_area_km2=cfg.unit_area_km2,
                            model_mode="lumped",
                            unit_count=1,
                            partition_method="full-basin (no DEM partition)",
                            note="lumped: one XAJ",
                        ),
                    )
                    area = usgs_area
                    unit_count = 1
                    partition_method = "full-basin (no DEM partition)"

                try:
                    from hydro_agent.modeling.review_map import render_basin_review_map

                    # Distributed already wrote real units.geojson; lumped falls back to one polygon.
                    if cfg.model_mode == "lumped" and not (gis / "units.geojson").is_file():
                        from hydro_agent.modeling.review_map import write_units_geojson

                        outlet_xy = None
                        if (gis / "outlet.geojson").is_file():
                            outlet_fc = json.loads((gis / "outlet.geojson").read_text(encoding="utf-8"))
                            for feature in outlet_fc.get("features") or []:
                                geom = feature.get("geometry") or {}
                                if geom.get("type") == "Point":
                                    outlet_xy = (
                                        float(geom["coordinates"][0]),
                                        float(geom["coordinates"][1]),
                                    )
                                    break
                        write_units_geojson(gis, unit_count=1, outlet_xy=outlet_xy)
                    render_basin_review_map(
                        gis,
                        title=f"{basin_id} · {cfg.model_mode} · {unit_count} units",
                    )
                except Exception as map_exc:  # noqa: BLE001 - review can continue without map art
                    write_json(gis / "map_error.json", {"error": str(map_exc)})

                review = {str(f.relative_to(root)): digest(f) for f in gis.rglob("*") if f.is_file()}
                review["case/dem_config.json"] = digest(case / "dem_config.json")
                boundary_hash = hashlib.sha256(json.dumps(review, sort_keys=True).encode()).hexdigest()
                self._stage(plan_id, "M02_DELINEATE", "completed")
                self._stage(plan_id, "M03_REVIEW_BOUNDARY", "awaiting_review", "请确认出口、面积与计算单元")
                self._update(
                    plan_id,
                    status="awaiting_review",
                    boundary=boundary,
                    boundary_hash=boundary_hash,
                    review_files=review,
                    area_km2=area,
                    unit_count=unit_count,
                    partition_method=partition_method,
                )
                return

            self._stage(plan_id, "M04_BUILD_INPUTS", "running")
            self._build_inputs(plan_id, cfg)
            self._stage(plan_id, "M04_BUILD_INPUTS", "completed")
            self._stage(plan_id, "M05_VALIDATE_PLAN", "running")
            self._normalize(plan_id, cfg)
            files = {
                str(f.relative_to(root)): digest(f)
                for folder in ("case", "normalized")
                for f in (root / folder).rglob("*")
                if f.is_file()
            }
            files["scheme.json"] = digest(root / "scheme.json")
            content_hash = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
            self._stage(plan_id, "M05_VALIDATE_PLAN", "completed")
            self._update(plan_id, status="ready", files=files, content_hash=content_hash)
        except Exception as exc:  # noqa: BLE001
            p = self.get(plan_id)
            if p.get("current_stage"):
                self._stage(plan_id, p["current_stage"], "failed", str(exc))
            self._update(plan_id, status="failed", error=str(exc))

    def _build_inputs(self, plan_id: str, cfg: UsPlanRequest) -> None:
        root = self.directory(plan_id)
        case = root / "case"
        hydro = self.catalog.hydro_dir(cfg.basin_id)
        forcing = [json.loads(line) for line in (hydro / "forcing.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        flow = [json.loads(line) for line in (hydro / "flow.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        by_date = {row["valid_date"]: row for row in flow}
        dates = [row["valid_date"] for row in forcing]
        if not dates:
            raise ValueError("forcing empty")
        units = list(csv.DictReader((case / "gis" / "units.csv").open(encoding="utf-8")))
        inputs = case / "model_inputs"
        if inputs.exists():
            shutil.rmtree(inputs)
        inputs.mkdir()
        # Uniform MultiMet field across units (documented assumption).
        with (inputs / "precipitation_mm.csv").open("w", encoding="utf-8", newline="") as rain_f, (
            inputs / "evaporation_mm.csv"
        ).open("w", encoding="utf-8", newline="") as pet_f, (inputs / "observed.csv").open(
            "w", encoding="utf-8", newline=""
        ) as obs_f:
            unit_cols = [f"unit_{u['unit_id']}" for u in units]
            rain_w = csv.DictWriter(rain_f, fieldnames=["time", *unit_cols])
            pet_w = csv.DictWriter(pet_f, fieldnames=["time", *unit_cols])
            obs_w = csv.DictWriter(
                obs_f,
                fieldnames=[
                    "time",
                    "discharge",
                    "source",
                    "available_at",
                    "eligible_for_scoring",
                    "quality_code",
                    "quality_note",
                ],
            )
            rain_w.writeheader()
            pet_w.writeheader()
            obs_w.writeheader()
            for row in forcing:
                day = row["valid_date"]
                rain = {col: float(row["precipitation_mm_day"]) for col in unit_cols}
                pet = {col: float(row["pet_mm_day"]) for col in unit_cols}
                rain_w.writerow({"time": day, **rain})
                pet_w.writerow({"time": day, **pet})
                if day not in by_date:
                    raise ValueError(f"missing discharge for {day}")
                flow_row = by_date[day]
                obs_w.writerow(
                    {
                        "time": day,
                        "discharge": float(flow_row["discharge_m3s"]),
                        "source": flow_row.get("source") or "",
                        "available_at": flow_row.get("available_at") or "",
                        "eligible_for_scoring": (
                            "true" if bool(flow_row.get("eligible_for_scoring", True)) else "false"
                        ),
                        "quality_code": flow_row.get("quality_code") or "",
                        "quality_note": flow_row.get("quality_note") or "",
                    }
                )
        params_dir = case / "parameters"
        params_dir.mkdir(exist_ok=True)
        # Teacher-native lowercase row for potential lab replay; product scheme uses DEFAULT_PARAMS.
        native_rows = []
        for unit in units:
            native_rows.append(
                dict(
                    kc=DEFAULT_PARAMS["K"],
                    b=DEFAULT_PARAMS["B"],
                    imp=DEFAULT_PARAMS["IM"],
                    wum=DEFAULT_PARAMS["UM"],
                    wlm=DEFAULT_PARAMS["LM"],
                    c=DEFAULT_PARAMS["C"],
                    sm=DEFAULT_PARAMS["SM"],
                    ex=DEFAULT_PARAMS["EX"],
                    ki=DEFAULT_PARAMS["KI"],
                    kg=DEFAULT_PARAMS["KG"],
                    cs=DEFAULT_PARAMS["CS"],
                    lag=DEFAULT_PARAMS["L"],
                    ci=DEFAULT_PARAMS["CI"],
                    cg=DEFAULT_PARAMS["CG"],
                    wm=DEFAULT_PARAMS["UM"] + DEFAULT_PARAMS["LM"] + DEFAULT_PARAMS["DM"],
                    rivid=int(unit["unit_id"]),
                    area=float(unit["area_km2"]),
                    dp=1,
                    ke=24.0,
                    xe=0.2,
                )
            )
        with (params_dir / "parameters.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(native_rows[0].keys()))
            writer.writeheader()
            writer.writerows(native_rows)
        write_json(
            case / "config" / "model_assumptions.json",
            dict(
                agent_used=False,
                model_mode=cfg.model_mode,
                precipitation=(
                    "gridMET NCSS gauge-point P (scale 0.1) applied uniformly to all units"
                    if (hydro / "source-manifest.json").is_file()
                    and "gridmet" in (hydro / "source-manifest.json").read_text(encoding="utf-8")
                    else "Caravan MultiMet ERA5-Land basin-mean applied uniformly to all units"
                ),
                evaporation=(
                    "gridMET NCSS PET (scale 0.1) applied uniformly"
                    if (hydro / "source-manifest.json").is_file()
                    and "gridmet" in (hydro / "source-manifest.json").read_text(encoding="utf-8")
                    else "FAO PM PET basin-mean applied uniformly"
                ),
                observed_discharge="USGS NWIS DV 00060 outlet only",
                warmup_days=cfg.warmup_days,
                unit_count=len(units),
                partition=(
                    "pyflwdir subbasins_area (DEM)"
                    if cfg.model_mode == "distributed"
                    else "full-basin lumped"
                ),
            ),
        )

    def _normalize(self, plan_id: str, cfg: UsPlanRequest) -> None:
        root = self.directory(plan_id)
        case = root / "case"
        units = list(csv.DictReader((case / "gis" / "units.csv").open(encoding="utf-8")))
        # Forecast adapter consumes lumped outlet series; multi-unit plans still export one outlet series
        # (uniform forcing → same as lumped hydrograph for product path). Keep unit table for audit.
        scheme = XajScheme(
            warmup_days=cfg.warmup_days,
            parameters=dict(DEFAULT_PARAMS),
            routing=dict(dp=0, ke=24.0, xe=0.2),
        )
        rain = list(csv.DictReader((case / "model_inputs" / "precipitation_mm.csv").open(encoding="utf-8")))
        evap = list(csv.DictReader((case / "model_inputs" / "evaporation_mm.csv").open(encoding="utf-8")))
        obs = list(csv.DictReader((case / "model_inputs" / "observed.csv").open(encoding="utf-8")))
        if [r["time"] for r in rain] != [r["time"] for r in evap] or [r["time"] for r in rain] != [r["time"] for r in obs]:
            raise ValueError("雨量、蒸发和观测日期未对齐")
        dates = [date.fromisoformat(r["time"][:10]) for r in rain]
        if any(b - a != timedelta(days=1) for a, b in zip(dates, dates[1:])):
            raise ValueError("输入日期不连续")
        norm = root / "normalized"
        if norm.exists():
            shutil.rmtree(norm)
        norm.mkdir()
        # Use unit_1 columns (uniform field).
        for name, data in [("forcing", rain), ("flow", obs)]:
            with (norm / f"{name}.jsonl").open("w", encoding="utf-8") as out:
                for i, row in enumerate(data):
                    available = datetime.combine(dates[i] + timedelta(days=1), time(0), ZoneInfo("UTC"))
                    item = dict(
                        valid_date=str(dates[i]),
                        available_at=row.get("available_at") or available.isoformat(),
                        source=(
                            row.get("source")
                            or (
                                "open-gridmet-usgs"
                                if cfg.basin_id.startswith("usgs_")
                                else "us-camels-multimet"
                            )
                        ),
                    )
                    if name == "forcing":
                        item.update(
                            precipitation_mm_day=float(row["unit_1"]),
                            pet_mm_day=float(evap[i]["unit_1"]),
                            source_kind="reanalysis",
                        )
                    else:
                        item.update(
                            discharge_m3s=float(row["discharge"]),
                            eligible_for_scoring=_parse_csv_bool(
                                row.get("eligible_for_scoring"), default=True
                            ),
                            quality_code=row.get("quality_code") or None,
                            quality_note=row.get("quality_note") or None,
                        )
                    out.write(json.dumps(item, allow_nan=False) + "\n")
        area = sum(float(u["area_km2"]) for u in units)
        write_json(
            norm / "basin.json",
            dict(
                basin_id=cfg.basin_id,
                area_km2=area,
                day_timezone="UTC",
            ),
        )
        write_json(
            norm / "basin_meta.json",
            dict(
                model_plan_id=plan_id,
                model_mode=cfg.model_mode,
                unit_count=len(units),
                time_semantics="USGS daily; UTC midnight availability policy",
                adapter="open-v1" if cfg.basin_id.startswith("usgs_") else "multimet-legacy",
            ),
        )
        from hydro_agent.data.lowman import load_normalized_source

        load_normalized_source(norm)
        write_json(
            root / "scheme.json",
            {
                **scheme.model_dump(),
                "model_version": MODEL_VERSION,
                "model_plan_id": plan_id,
                "basin_id": cfg.basin_id,
                "model_mode": cfg.model_mode,
            },
        )
        warmup = cfg.warmup_days
        # RealWorkbenchKernel uses history_days = max(60, warmup + 60); snapshots need
        # that many forcing days before each issue plus three lead days after.
        history_days = max(60, warmup + 60)
        sug_start, sug_end = recommended_task_window(dates[0], dates[-1], history_days)
        self._update(
            plan_id,
            area_km2=area,
            unit_count=len(units),
            data_start=str(dates[0]),
            data_end=str(dates[-1]),
            suggested_start=str(sug_start),
            suggested_end=str(sug_end),
            history_days=history_days,
        )
