from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from hydro_agent.calibration.dataset import CalibrationDatasetPlan, plan_calibration_dataset
from hydro_agent.calibration.signatures import HydrologicSignatures, compute_hydrologic_signatures
from hydro_agent.evaluation.gbt22482 import HydroSeries
from hydro_agent.models.xaj.contracts import XajBasin, XajScheme
from hydro_agent.models.xaj.upstream import simulate
from hydro_agent.workbench.validation_gate import ValidationWindow


@dataclass(frozen=True)
class CalibrationPlan:
    calibration: ValidationWindow
    development: ValidationWindow
    final_holdout: ValidationWindow
    dataset: CalibrationDatasetPlan | None = None


class CalibrationEvaluationService:
    """Continuous multi-year evaluation + hydrologic signatures for one XAJ scheme."""

    def __init__(self, *, repository, source, task_configs: dict):
        self.repository = repository
        self.source = source
        self.task_configs = task_configs
        self._auto_plans: dict[str, CalibrationDatasetPlan] = {}

    @staticmethod
    def _day(value, fallback: str | None = None) -> date | None:
        raw = value or fallback
        if raw is None:
            return None
        return date.fromisoformat(raw[:10]) if isinstance(raw, str) else raw

    def _automatic_plan(self, task_id: str, cfg: dict) -> CalibrationPlan:
        if task_id not in self._auto_plans:
            requested_start = self._day(cfg.get("start_date"))
            requested_end = self._day(cfg.get("end_date"))
            dated_flow = tuple(
                (row.valid_date, float(row.discharge_m3s)) for row in self.source.flow_rows
            )
            self._auto_plans[task_id] = plan_calibration_dataset(
                dated_flow,
                record_start=requested_start,
                record_end=requested_end,
            )
        dataset = self._auto_plans[task_id]
        return CalibrationPlan(
            calibration=ValidationWindow(dataset.calibration.start, dataset.calibration.end),
            development=ValidationWindow(dataset.development.start, dataset.development.end),
            final_holdout=ValidationWindow(dataset.final_holdout.start, dataset.final_holdout.end),
            dataset=dataset,
        )

    def plan_for(self, task_id: str) -> CalibrationPlan:
        cfg = self.task_configs.get(task_id) or {}
        explicit = all(
            cfg.get(key)
            for key in (
                "calibration_start_date",
                "calibration_end_date",
                "gate_start_date",
                "gate_end_date",
            )
        )
        if not explicit:
            return self._automatic_plan(task_id, cfg)

        cal_start = self._day(cfg.get("calibration_start_date"), "2011-01-01")
        cal_end = self._day(cfg.get("calibration_end_date"), "2017-12-31")
        dev_start = self._day(cfg.get("gate_start_date"), "2018-01-01")
        dev_end = self._day(cfg.get("gate_end_date"), "2019-12-31")
        final_start = self._day(cfg.get("final_start_date") or cfg.get("start_date"), "2020-04-01")
        final_end = self._day(cfg.get("final_end_date") or cfg.get("end_date"), "2020-07-31")
        assert cal_start and cal_end and dev_start and dev_end and final_start and final_end
        if not (cal_start <= cal_end < dev_start <= dev_end < final_start <= final_end):
            raise ValueError("calibration, development and final holdout windows must be ordered and disjoint")
        return CalibrationPlan(
            calibration=ValidationWindow(cal_start, cal_end),
            development=ValidationWindow(dev_start, dev_end),
            final_holdout=ValidationWindow(final_start, final_end),
        )

    def window_for(self, task_id: str) -> ValidationWindow:
        return self.plan_for(task_id).development

    def calibration_window_for(self, task_id: str) -> ValidationWindow:
        return self.plan_for(task_id).calibration

    def evaluate_scheme(
        self,
        scheme_id: str,
        window: ValidationWindow,
    ) -> tuple[HydroSeries, HydrologicSignatures]:
        import numpy as np

        row = self.repository.get_scheme(scheme_id)
        cfg = dict(row.config_json or {})
        scheme = XajScheme(
            model_id="xaj",
            warmup_days=int(cfg.get("warmup_days") or 365),
            parameters=dict(cfg.get("parameters") or {}),
            routing=cfg.get("routing") or {},
        )
        basin = XajBasin(**dict(self.source.basin))
        first = window.start - timedelta(days=scheme.warmup_days)
        forcing_by_day = {r.valid_date: r for r in self.source.forcing_rows}
        truth = {r.valid_date: float(r.discharge_m3s) for r in self.source.flow_rows}

        days: list[date] = []
        cur = first
        while cur <= window.end:
            days.append(cur)
            cur += timedelta(days=1)
        missing = [d for d in days if d not in forcing_by_day]
        if missing:
            raise RuntimeError(f"forcing incomplete: {missing[0]}..{missing[-1]}")

        inputs = np.asarray(
            [
                [
                    float(forcing_by_day[d].precipitation_mm_day),
                    float(forcing_by_day[d].pet_mm_day),
                ]
                for d in days
            ],
            dtype=float,
        )[:, None, :]
        values = simulate(scheme, basin, inputs)
        sim_days = days[scheme.warmup_days :]
        aligned = [
            (d, float(truth[d]), float(q), float(forcing_by_day[d].precipitation_mm_day))
            for d, q in zip(sim_days, values)
            if window.start <= d <= window.end and d in truth
        ]
        if len(aligned) < 30:
            raise RuntimeError("calibration evaluation requires at least 30 observed daily pairs")

        obs = tuple(row[1] for row in aligned)
        sim = tuple(row[2] for row in aligned)
        precip = tuple(row[3] for row in aligned)
        times = tuple(datetime(d.year, d.month, d.day, tzinfo=timezone.utc) for d, *_ in aligned)
        hydro = HydroSeries(
            obs=obs,
            sim=sim,
            times=times,
            dt_hours=24.0,
            area_km2=float(basin.area_km2),
        )
        signatures = compute_hydrologic_signatures(
            obs,
            sim,
            times=times,
            precipitation_mm=precip,
            area_km2=float(basin.area_km2),
            dt_hours=24.0,
        )
        return hydro, signatures
