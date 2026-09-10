"""Product model-plan service with real spatial XAJ preparation.

The legacy US plan service is retained for compatibility. New product plans use
pyflwdir subbasins and, for distributed USGS cases, fetch gridMET at each subbasin
representative point. No equal-area or duplicated-forcing fallback is permitted.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from hydro_agent.data.contracts import FlowObservation, ForcingRow, UnitForcing
from hydro_agent.modeling.plans import digest, write_json
from hydro_agent.modeling.spatial import build_lumped_units, build_pyflwdir_units
from hydro_agent.modeling.us_plans import DEFAULT_PARAMS, UsModelPlanService, UsPlanRequest
from hydro_agent.models.xaj.contracts import XajScheme
from hydro_agent.models.xaj.upstream import MODEL_SHA256, MODEL_VERSION


class ProductUsModelPlanService(UsModelPlanService):
    """Model preparation used by the product-facing workbench."""

    def _write_units_csv(self, path, units) -> None:
        rows = [dict(unit) for unit in units]
        fields = ["unit_id", "area_km2", "source", "centroid_lon", "centroid_lat"]
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                row.setdefault("centroid_lon", "")
                row.setdefault("centroid_lat", "")
                writer.writerow(row)

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
                self._stage(plan_id, "M00_ENSURE_MATERIALS", "completed", "长期水文资料可用")
                self._stage(plan_id, "M02_DELINEATE", "running")

                case = root / "case"
                gis = case / "gis"
                case.mkdir(exist_ok=True)
                gis.mkdir(exist_ok=True)
                src_gis = self.catalog.gis_dir(basin_id)
                for name in (
                    "boundary.geojson",
                    "outlet.geojson",
                    "bbox.json",
                    "boundary_check.json",
                    "nldi_feature.json",
                    "flowlines.geojson",
                ):
                    if (src_gis / name).is_file():
                        shutil.copy2(src_gis / name, gis / name)

                basin = json.loads((hydro / "basin.json").read_text(encoding="utf-8"))
                source_area = float(basin["area_km2"])
                if cfg.model_mode == "lumped":
                    spatial = build_lumped_units(area_km2=source_area)
                    self._write_units_csv(gis / "units.csv", spatial.units)
                    try:
                        from hydro_agent.modeling.review_map import write_units_geojson

                        outlet_xy = None
                        outlet_path = gis / "outlet.geojson"
                        if outlet_path.is_file():
                            outlet = json.loads(outlet_path.read_text(encoding="utf-8"))
                            for feature in outlet.get("features") or []:
                                geom = feature.get("geometry") or {}
                                if geom.get("type") == "Point":
                                    outlet_xy = tuple(geom["coordinates"][:2])
                                    break
                        write_units_geojson(gis, unit_count=1, outlet_xy=outlet_xy)
                    except Exception as exc:  # noqa: BLE001
                        write_json(gis / "map_units_error.json", {"error": str(exc)})
                else:
                    spatial = build_pyflwdir_units(
                        dem_dir=self.catalog.dem_dir(basin_id),
                        gis_dir=src_gis,
                        output_dir=gis,
                        unit_area_km2=cfg.unit_area_km2,
                        stream_area_km2=cfg.stream_area_km2,
                    )

                units = list(spatial.units)
                model_area = sum(float(unit["area_km2"]) for unit in units)
                boundary_path = gis / "boundary_check.json"
                if boundary_path.is_file():
                    boundary = json.loads(boundary_path.read_text(encoding="utf-8"))
                else:
                    boundary = {"accepted": True, "usgs_area_km2": source_area}
                boundary.update(
                    model_mode=cfg.model_mode,
                    unit_count=len(units),
                    dem_area_km2=model_area,
                    spatial_method=spatial.spatial_method,
                    note=(
                        "集总式：全流域一套 XAJ。"
                        if cfg.model_mode == "lumped"
                        else (
                            f"分布式：pyflwdir 基于 DEM 自动形成 {len(units)} 个真实子流域；"
                            "确认后将按子流域代表点分别获取 gridMET 强迫。"
                        )
                    ),
                )
                write_json(boundary_path, boundary)
                write_json(
                    case / "dem_config.json",
                    {
                        "resolution_m": cfg.resolution_m,
                        "stream_area_km2": cfg.stream_area_km2,
                        "unit_area_km2": cfg.unit_area_km2,
                        "model_mode": cfg.model_mode,
                        "unit_count": len(units),
                        "spatial_method": spatial.spatial_method,
                    },
                )

                try:
                    from hydro_agent.modeling.review_map import render_basin_review_map

                    render_basin_review_map(
                        gis,
                        title=f"{basin_id} · {cfg.model_mode} · {len(units)} units",
                    )
                except Exception as map_exc:  # noqa: BLE001
                    write_json(gis / "map_error.json", {"error": str(map_exc)})

                review = {
                    str(file.relative_to(root)): digest(file)
                    for file in gis.rglob("*")
                    if file.is_file()
                }
                review["case/dem_config.json"] = digest(case / "dem_config.json")
                boundary_hash = hashlib.sha256(
                    json.dumps(review, sort_keys=True).encode()
                ).hexdigest()
                self._stage(plan_id, "M02_DELINEATE", "completed")
                self._stage(
                    plan_id,
                    "M03_REVIEW_BOUNDARY",
                    "awaiting_review",
                    "请确认出口、真实子流域边界与计算单元",
                )
                self._update(
                    plan_id,
                    status="awaiting_review",
                    boundary=boundary,
                    boundary_hash=boundary_hash,
                    review_files=review,
                    area_km2=model_area,
                    unit_count=len(units),
                    spatial_method=spatial.spatial_method,
                )
                return

            self._stage(plan_id, "M04_BUILD_INPUTS", "running")
            self._build_inputs(plan_id, cfg)
            self._stage(plan_id, "M04_BUILD_INPUTS", "completed")
            self._stage(plan_id, "M05_VALIDATE_PLAN", "running")
            self._normalize(plan_id, cfg)
            files = {
                str(file.relative_to(root)): digest(file)
                for folder in ("case", "normalized")
                for file in (root / folder).rglob("*")
                if file.is_file()
            }
            files["scheme.json"] = digest(root / "scheme.json")
            content_hash = hashlib.sha256(
                json.dumps(files, sort_keys=True).encode()
            ).hexdigest()
            self._stage(plan_id, "M05_VALIDATE_PLAN", "completed")
            self._update(plan_id, status="ready", files=files, content_hash=content_hash)
        except Exception as exc:  # noqa: BLE001
            p = self.get(plan_id)
            if p.get("current_stage"):
                self._stage(plan_id, p["current_stage"], "failed", str(exc))
            self._update(plan_id, status="failed", error=str(exc))

    def _build_inputs(self, plan_id: str, cfg: UsPlanRequest) -> None:
        if cfg.model_mode == "lumped":
            return super()._build_inputs(plan_id, cfg)
        if not cfg.basin_id.startswith("usgs_"):
            raise ValueError(
                "当前分布式产品仅允许可按子流域代表点获取 gridMET 的 USGS open-v1 流域；"
                "禁止把 basin-mean forcing 复制到多个单元"
            )

        from hydro_agent.data.adapters.open_basin import fetch_gridmet_forcing

        root = self.directory(plan_id)
        case = root / "case"
        hydro = self.catalog.hydro_dir(cfg.basin_id)
        units = list(csv.DictReader((case / "gis" / "units.csv").open(encoding="utf-8")))
        if any(not row.get("centroid_lon") or not row.get("centroid_lat") for row in units):
            raise ValueError("distributed 子流域缺少代表点，不能构建空间强迫")

        flow_rows = [
            json.loads(line)
            for line in (hydro / "flow.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        base_forcing = [
            json.loads(line)
            for line in (hydro / "forcing.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        flow_by_day = {row["valid_date"]: row for row in flow_rows}
        source_days = sorted(
            set(row["valid_date"] for row in base_forcing) & set(flow_by_day)
        )
        if len(source_days) < 365 * 5:
            raise ValueError("自动率定至少需要约 5 年连续历史资料；建议准备 8–10 年")
        start = date.fromisoformat(source_days[0])
        end = date.fromisoformat(source_days[-1])

        forcing_by_unit: dict[int, dict[str, object]] = {}
        for row in units:
            unit_id = int(row["unit_id"])
            forcing = fetch_gridmet_forcing(
                latitude=float(row["centroid_lat"]),
                longitude=float(row["centroid_lon"]),
                start=start,
                end=end,
            )
            forcing_by_unit[unit_id] = {item.valid_date.isoformat(): item for item in forcing}

        common_days = [
            day
            for day in source_days
            if all(day in forcing_by_unit[int(unit["unit_id"])] for unit in units)
        ]
        expected = (end - start).days + 1
        if len(common_days) < expected * 0.98:
            raise ValueError("分布式 gridMET 单元强迫缺测过多，拒绝生成伪完整方案")

        inputs = case / "model_inputs"
        if inputs.exists():
            shutil.rmtree(inputs)
        inputs.mkdir(parents=True)
        unit_cols = [f"unit_{int(unit['unit_id'])}" for unit in units]
        with (
            (inputs / "precipitation_mm.csv").open("w", encoding="utf-8", newline="") as rain_f,
            (inputs / "evaporation_mm.csv").open("w", encoding="utf-8", newline="") as pet_f,
            (inputs / "observed.csv").open("w", encoding="utf-8", newline="") as obs_f,
        ):
            rain_w = csv.DictWriter(rain_f, fieldnames=["time", *unit_cols])
            pet_w = csv.DictWriter(pet_f, fieldnames=["time", *unit_cols])
            obs_w = csv.DictWriter(obs_f, fieldnames=["time", "discharge"])
            rain_w.writeheader()
            pet_w.writeheader()
            obs_w.writeheader()
            for day in common_days:
                rain = {}
                pet = {}
                for unit in units:
                    unit_id = int(unit["unit_id"])
                    item = forcing_by_unit[unit_id][day]
                    rain[f"unit_{unit_id}"] = float(item.precipitation_mm_day)
                    pet[f"unit_{unit_id}"] = float(item.pet_mm_day)
                rain_w.writerow({"time": day, **rain})
                pet_w.writerow({"time": day, **pet})
                obs_w.writerow(
                    {"time": day, "discharge": float(flow_by_day[day]["discharge_m3s"])}
                )

        params_dir = case / "parameters"
        params_dir.mkdir(exist_ok=True)
        native_rows = []
        for unit in units:
            native_rows.append(
                {
                    "kc": DEFAULT_PARAMS["K"],
                    "b": DEFAULT_PARAMS["B"],
                    "imp": DEFAULT_PARAMS["IM"],
                    "wum": DEFAULT_PARAMS["UM"],
                    "wlm": DEFAULT_PARAMS["LM"],
                    "c": DEFAULT_PARAMS["C"],
                    "sm": DEFAULT_PARAMS["SM"],
                    "ex": DEFAULT_PARAMS["EX"],
                    "ki": DEFAULT_PARAMS["KI"],
                    "kg": DEFAULT_PARAMS["KG"],
                    "cs": DEFAULT_PARAMS["CS"],
                    "lag": DEFAULT_PARAMS["L"],
                    "ci": DEFAULT_PARAMS["CI"],
                    "cg": DEFAULT_PARAMS["CG"],
                    "wm": DEFAULT_PARAMS["UM"] + DEFAULT_PARAMS["LM"] + DEFAULT_PARAMS["DM"],
                    "rivid": int(unit["unit_id"]),
                    "area": float(unit["area_km2"]),
                    "dp": 1,
                    "ke": 24.0,
                    "xe": 0.2,
                }
            )
        with (params_dir / "parameters.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(native_rows[0].keys()))
            writer.writeheader()
            writer.writerows(native_rows)

        config_dir = case / "config"
        config_dir.mkdir(exist_ok=True)
        write_json(
            config_dir / "model_assumptions.json",
            {
                "agent_used": False,
                "model_mode": "distributed",
                "spatial_method": "pyflwdir-subbasins-area",
                "precipitation": "gridMET NCSS sampled independently at each subbasin representative point",
                "evaporation": "gridMET grass-reference PET sampled independently at each subbasin representative point",
                "observed_discharge": "USGS NWIS DV 00060 outlet only",
                "routing": "teacher XAJ multi-zone sum_qsig; no explicit inter-subbasin river routing claimed",
                "warmup_days": cfg.warmup_days,
                "unit_count": len(units),
            },
        )

    def _normalize(self, plan_id: str, cfg: UsPlanRequest) -> None:
        if cfg.model_mode == "lumped":
            return super()._normalize(plan_id, cfg)

        root = self.directory(plan_id)
        case = root / "case"
        units = list(csv.DictReader((case / "gis" / "units.csv").open(encoding="utf-8")))
        rain = list(
            csv.DictReader((case / "model_inputs" / "precipitation_mm.csv").open(encoding="utf-8"))
        )
        evap = list(
            csv.DictReader((case / "model_inputs" / "evaporation_mm.csv").open(encoding="utf-8"))
        )
        obs = list(csv.DictReader((case / "model_inputs" / "observed.csv").open(encoding="utf-8")))
        if [row["time"] for row in rain] != [row["time"] for row in evap] or [
            row["time"] for row in rain
        ] != [row["time"] for row in obs]:
            raise ValueError("雨量、蒸发和观测日期未对齐")
        dates = [date.fromisoformat(row["time"][:10]) for row in rain]
        if any(right - left != timedelta(days=1) for left, right in zip(dates, dates[1:])):
            raise ValueError("分布式输入日期不连续")

        unit_specs = [
            {
                "unit_id": int(unit["unit_id"]),
                "area_km2": float(unit["area_km2"]),
                "centroid_lon": float(unit["centroid_lon"]),
                "centroid_lat": float(unit["centroid_lat"]),
            }
            for unit in units
        ]
        area = sum(float(unit["area_km2"]) for unit in unit_specs)
        scheme = XajScheme(
            warmup_days=cfg.warmup_days,
            parameters=dict(DEFAULT_PARAMS),
            routing={"dp": 0, "ke": 24.0, "xe": 0.2},
            units=tuple(unit_specs),
        )

        norm = root / "normalized"
        if norm.exists():
            shutil.rmtree(norm)
        norm.mkdir()
        with (norm / "forcing.jsonl").open("w", encoding="utf-8") as forcing_out, (
            norm / "flow.jsonl"
        ).open("w", encoding="utf-8") as flow_out:
            for index, day in enumerate(dates):
                available = datetime.combine(day + timedelta(days=1), time(0), ZoneInfo("UTC"))
                spatial_forcing = []
                weighted_p = 0.0
                weighted_pet = 0.0
                for unit in unit_specs:
                    unit_id = int(unit["unit_id"])
                    p = float(rain[index][f"unit_{unit_id}"])
                    pet = float(evap[index][f"unit_{unit_id}"])
                    unit_area = float(unit["area_km2"])
                    weighted_p += p * unit_area
                    weighted_pet += pet * unit_area
                    spatial_forcing.append(
                        UnitForcing(
                            unit_id=unit_id,
                            precipitation_mm_day=p,
                            pet_mm_day=pet,
                        )
                    )
                forcing = ForcingRow(
                    valid_date=day,
                    precipitation_mm_day=weighted_p / area,
                    pet_mm_day=weighted_pet / area,
                    source_kind="reanalysis",
                    source="gridmet-subbasin-centroids",
                    available_at=available,
                    units=tuple(spatial_forcing),
                )
                flow = FlowObservation(
                    valid_date=day,
                    discharge_m3s=float(obs[index]["discharge"]),
                    source="usgs-nwis-dv-00060",
                    available_at=available,
                )
                forcing_out.write(forcing.model_dump_json() + "\n")
                flow_out.write(flow.model_dump_json() + "\n")

        write_json(
            norm / "basin.json",
            {"basin_id": cfg.basin_id, "area_km2": area, "day_timezone": "UTC"},
        )
        write_json(
            norm / "basin_meta.json",
            {
                "model_plan_id": plan_id,
                "model_mode": "distributed",
                "unit_count": len(unit_specs),
                "spatial_method": "pyflwdir-subbasins-area",
                "forcing_method": "gridmet-subbasin-centroids",
                "time_semantics": "USGS daily; UTC midnight availability policy",
                "adapter": "open-v1-distributed",
            },
        )
        from hydro_agent.data.lowman import load_normalized_source

        load_normalized_source(norm)
        write_json(
            root / "scheme.json",
            {
                **scheme.model_dump(mode="json"),
                "model_version": MODEL_VERSION,
                "model_source_sha256": MODEL_SHA256,
                "model_plan_id": plan_id,
                "basin_id": cfg.basin_id,
                "model_mode": "distributed",
                "spatial_method": "pyflwdir-subbasins-area",
            },
        )

        history_days = max(60, cfg.warmup_days + 60)
        first_issue = dates[0] + timedelta(days=history_days - 1)
        last_issue = dates[-1] - timedelta(days=3)
        if last_issue <= first_issue:
            raise ValueError("历史资料长度不足，无法同时满足预热、率定和独立验证")
        suggested_start = first_issue + timedelta(days=1)
        suggested_end = min(suggested_start + timedelta(days=14), last_issue)
        self._update(
            plan_id,
            area_km2=area,
            unit_count=len(unit_specs),
            data_start=str(dates[0]),
            data_end=str(dates[-1]),
            suggested_start=str(suggested_start),
            suggested_end=str(suggested_end),
            history_days=history_days,
            forcing_method="gridmet-subbasin-centroids",
        )
