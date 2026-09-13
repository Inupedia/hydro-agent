from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from hydro_agent.evaluation.evidence import HydrologicEvidenceBuilder
from hydro_agent.evaluation.evidence_summary import annual_stability_evidence
from hydro_agent.evaluation.hydrograph import build_comparison, write_bundle
from hydro_agent.evaluation.metrics import bias, kge, mae, nse
from hydro_agent.replay.contracts import ReplayEvaluation


class EvaluationService:
    def __init__(self, repository, *, snapshot_root: Path, observation_loader=None):
        self.repository = repository
        self.snapshot_root = Path(snapshot_root)
        self.observation_loader = observation_loader or self._load_streamflow

    def evaluate(
        self,
        task_id: str,
        observation_snapshot_id: str,
        *,
        output_dir: Path | None = None,
    ) -> ReplayEvaluation:
        task = self.repository.get_task(task_id)
        if task.phase != "E":
            raise ValueError("evaluation requires E phase")
        state = self.repository.ensure_task_state(task_id)
        scheme = self.repository.get_scheme(state.current_scheme_id)
        if scheme.status != "frozen":
            raise ValueError("evaluation requires frozen scheme")
        snapshot = self.repository.get_snapshot(observation_snapshot_id)
        if snapshot.task_id != task_id:
            raise ValueError("cross-task references are forbidden")
        truth = self.observation_loader(observation_snapshot_id)
        quality_by_date = self._quality_by_date(observation_snapshot_id)
        final_test_window = self._final_test_window_from_scheme(scheme)
        forecasts = [
            row
            for row in self.repository.list_forecasts(task_id)
            if row.scheme_id == scheme.scheme_id
        ]
        forecasts.sort(key=lambda row: row.issue_time)
        lead_obs: dict[int, list[float]] = {1: [], 2: [], 3: []}
        lead_sim: dict[int, list[float]] = {1: [], 2: [], 3: []}
        for forecast in forecasts:
            issue_date = forecast.issue_time.date()
            for lead, value in forecast.lead_values_json.items():
                lead_i = int(lead)
                target = issue_date + timedelta(days=lead_i)
                if target not in truth:
                    continue
                if final_test_window is not None:
                    final_start, final_end = final_test_window
                    if target < final_start or target > final_end:
                        continue
                lead_obs[lead_i].append(float(truth[target]))
                lead_sim[lead_i].append(float(value))
        lead_metrics: dict[str, dict[str, float]] = {}
        sample_counts: dict[str, int] = {}
        for lead in (1, 2, 3):
            obs = lead_obs[lead]
            sim = lead_sim[lead]
            sample_counts[f"lead_{lead}"] = len(obs)
            if len(obs) < 2:
                continue
            lead_metrics[f"lead_{lead}"] = {
                "NSE": nse(obs, sim),
                "KGE": kge(obs, sim),
                "MAE": mae(obs, sim),
                "Bias": bias(obs, sim),
            }
        if not lead_metrics:
            raise ValueError("insufficient observation pairs for evaluation")

        rolling_metrics = {
            key: float(sum(item[key] for item in lead_metrics.values()) / len(lead_metrics))
            for key in ("NSE", "KGE", "MAE", "Bias")
        }

        gbt_payload: dict = {}
        try:
            from hydro_agent.evaluation.gbt22482 import HydroSeries, build_gbt_accuracy_report
            from hydro_agent.skills import SkillRegistry

            obs_all: list[float] = []
            sim_all: list[float] = []
            for lead in (1, 2, 3):
                obs_all.extend(lead_obs[lead])
                sim_all.extend(lead_sim[lead])
            if len(obs_all) >= 2:
                cfg = SkillRegistry().gbt_accuracy_config()
                report = build_gbt_accuracy_report(
                    HydroSeries(obs=tuple(obs_all), sim=tuple(sim_all)),
                    cfg,
                )
                gbt_payload = report.model_dump()
                rolling_metrics.update(report.as_metrics_dict())
        except Exception as exc:  # noqa: BLE001
            gbt_payload = {"error": str(exc)}
        provenance = dict((scheme.config_json or {}).get("provenance") or {})
        if gbt_payload:
            provenance = {**provenance, "gbt_22482": gbt_payload}
        if final_test_window is not None:
            final_start, final_end = final_test_window
            provenance = {
                **provenance,
                "final_test_window": {
                    "start": final_start.isoformat(),
                    "end": final_end.isoformat(),
                },
            }
        excluded_quality = sum(not eligible for eligible in quality_by_date.values())
        provenance = {
            **provenance,
            "observation_quality": {
                "source": "snapshot-manifest.flow_rows",
                "excluded_count": excluded_quality,
                "scoring_csv_contains_only_eligible": True,
            },
        }
        gate_status = self._latest_gate_status(task_id)
        frozen_is_candidate = gate_status == "ACCEPT"
        hydrograph = self._try_test_hydrograph(
            observation_snapshot_id,
            scheme,
            output_dir=output_dir,
            gate_status=gate_status,
            frozen_is_candidate=frozen_is_candidate,
        )
        continuous_metrics = self._continuous_metrics_from_hydrograph(hydrograph)
        hydrologic_evidence = self._hydrologic_evidence_from_hydrograph(
            hydrograph,
            quality_by_date=quality_by_date,
        )

        metrics = dict(rolling_metrics)
        metrics.update({f"rolling_{key}": float(value) for key, value in rolling_metrics.items()})
        metrics.update(
            {f"continuous_{key}": float(value) for key, value in continuous_metrics.items()}
        )

        return ReplayEvaluation(
            task_id=task_id,
            scheme_id=scheme.scheme_id,
            observation_snapshot_id=observation_snapshot_id,
            forecast_ids=tuple(row.forecast_id for row in forecasts),
            metrics=metrics,
            rolling_metrics=rolling_metrics,
            lead_metrics=lead_metrics,
            continuous_metrics=continuous_metrics,
            hydrologic_evidence=hydrologic_evidence,
            sample_counts=sample_counts,
            forcing_mode=task.forcing_mode,
            provenance=provenance,
            hydrograph=hydrograph,
        )

    @staticmethod
    def _final_test_window_from_scheme(scheme) -> tuple[date, date] | None:
        config = dict(scheme.config_json or {})
        workbench = dict(config.get("workbench") or {})
        raw_start = workbench.get("final_test_start_date")
        raw_end = workbench.get("final_test_end_date")
        if not raw_start or not raw_end:
            return None
        try:
            start = date.fromisoformat(str(raw_start)[:10])
            end = date.fromisoformat(str(raw_end)[:10])
        except ValueError:
            return None
        if end < start:
            return None
        return start, end

    @staticmethod
    def _continuous_metrics_from_hydrograph(hydrograph: dict | None) -> dict[str, float]:
        if not hydrograph:
            return {}
        frozen = hydrograph.get("frozen_metrics")
        if not isinstance(frozen, dict):
            return {}
        mapping = {
            "NSE": "nse",
            "KGE": "kge",
            "PBIAS": "pbias_percent",
            "RMSE": "rmse_m3s",
            "MAE": "mae",
            "HighFlowMAE": "high_flow_mae",
            "PeakRatio": "peak_ratio",
            "PeakTimingLagSteps": "peak_timing_lag_steps",
            "SampleCount": "count",
        }
        out: dict[str, float] = {}
        for output_key, source_key in mapping.items():
            value = frozen.get(source_key)
            if isinstance(value, (int, float)):
                out[output_key] = float(value)
        return out

    @staticmethod
    def _hydrologic_evidence_from_hydrograph(
        hydrograph: dict | None,
        *,
        quality_by_date: dict[date, bool] | None = None,
    ) -> dict[str, object]:
        if not hydrograph:
            return {}
        raw_series = hydrograph.get("series")
        if not isinstance(raw_series, list):
            return {}
        rows = [row for row in raw_series if isinstance(row, dict) and not row.get("is_warmup")]
        if not rows:
            return {}
        dates: list[date] = []
        observed: list[float | None] = []
        simulated: list[float | None] = []
        quality_mask: list[bool] = []
        for row in rows:
            raw_time = row.get("time")
            if not raw_time:
                continue
            try:
                day = date.fromisoformat(str(raw_time)[:10])
            except ValueError:
                continue
            dates.append(day)
            observed.append(row.get("observed_m3s"))
            simulated.append(row.get("frozen_m3s"))
            quality_mask.append(
                True if quality_by_date is None else bool(quality_by_date.get(day, False))
            )
        if not dates:
            return {}
        try:
            bundle = HydrologicEvidenceBuilder().build(
                window="final_test",
                dates=dates,
                observed=observed,
                simulated=simulated,
                quality_mask=quality_mask,
            )
        except ValueError:
            return {}
        payload = bundle.as_dict()
        payload["annual_stability"] = asdict(annual_stability_evidence(bundle))
        return payload

    def _quality_by_date(self, snapshot_id: str) -> dict[date, bool]:
        snapshot = self.repository.get_snapshot(snapshot_id)
        manifest = dict(snapshot.manifest_json or {})
        rows = manifest.get("flow_rows")
        if not isinstance(rows, list):
            return {}
        out: dict[date, bool] = {}
        for row in rows:
            if not isinstance(row, dict) or not row.get("valid_date"):
                continue
            try:
                day = date.fromisoformat(str(row["valid_date"])[:10])
            except ValueError:
                continue
            out[day] = bool(row.get("eligible_for_scoring", True))
        return out

    def _latest_gate_status(self, task_id: str) -> str | None:
        for row in reversed(self.repository.list_evidence(task_id)):
            if row.action == "A08_GATE":
                return str(row.status)
        return None

    def _snapshot_dir(self, snapshot_id: str) -> Path | None:
        path = self.snapshot_root / snapshot_id
        if (path / "streamflow.csv").is_file() or (path / "forcing.csv").is_file():
            return path
        matches = list(self.snapshot_root.rglob(f"{snapshot_id}/streamflow.csv"))
        if matches:
            return matches[0].parent
        matches = list(self.snapshot_root.rglob(f"{snapshot_id}/forcing.csv"))
        if matches:
            return matches[0].parent
        return None

    def _baseline_config_for_frozen(self, scheme) -> dict | None:
        frozen_cfg = dict(scheme.config_json or {})
        frozen_provenance = dict(frozen_cfg.get("provenance") or {})
        source_id = str(frozen_provenance.get("source_scheme_id") or "")
        if not source_id:
            return None
        try:
            source = self.repository.get_scheme(source_id)
        except KeyError:
            return None

        source_cfg = dict(source.config_json or {})
        if source.status == "base":
            return source_cfg

        source_provenance = dict(source_cfg.get("provenance") or {})
        base_id = str(
            source_provenance.get("base_scheme_id")
            or source_provenance.get("source_scheme_id")
            or ""
        )
        if not base_id:
            return None
        try:
            return dict(self.repository.get_scheme(base_id).config_json or {})
        except KeyError:
            return None

    def _try_test_hydrograph(
        self,
        observation_snapshot_id: str,
        scheme,
        *,
        output_dir: Path | None,
        gate_status: str | None,
        frozen_is_candidate: bool,
    ) -> dict | None:
        snapshot_dir = self._snapshot_dir(observation_snapshot_id)
        if snapshot_dir is None:
            return None
        forcing_path = snapshot_dir / "forcing.csv"
        basin_path = snapshot_dir / "basin.json"
        if not forcing_path.is_file() or not basin_path.is_file():
            return None
        cfg = dict(scheme.config_json or {})
        try:
            from datetime import date as date_cls

            import numpy as np

            from hydro_agent.models.xaj.contracts import XajBasin, XajScheme
            from hydro_agent.models.xaj.upstream import simulate

            xaj = XajScheme(
                model_id="xaj",
                warmup_days=int(cfg["warmup_days"]),
                parameters=cfg["parameters"],
                routing=cfg.get("routing") or {},
            )
            basin = XajBasin.model_validate_json(basin_path.read_text(encoding="utf-8"))
            with forcing_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            dates = [date_cls.fromisoformat(row["date"]) for row in rows]
            array = np.asarray(
                [
                    [float(row["precipitation_mm_day"]), float(row["pet_mm_day"])]
                    for row in rows
                ]
            )
            if len(dates) < xaj.warmup_days + 2:
                return None
            values = simulate(xaj, basin, array[:, None, :], include_warmup=True)

            baseline_values = None
            baseline_cfg = self._baseline_config_for_frozen(scheme)
            if baseline_cfg:
                try:
                    baseline_xaj = XajScheme(
                        model_id="xaj",
                        warmup_days=int(baseline_cfg.get("warmup_days", cfg["warmup_days"])),
                        parameters=baseline_cfg["parameters"],
                        routing=baseline_cfg.get("routing") or {},
                    )
                    baseline_values = simulate(
                        baseline_xaj, basin, array[:, None, :], include_warmup=True
                    )
                except Exception:  # noqa: BLE001
                    baseline_values = None

            observed = self.observation_loader(observation_snapshot_id)
            if not isinstance(observed, dict):
                return None

            final_test_window = self._final_test_window_from_scheme(scheme)
            if final_test_window is not None:
                final_start, final_end = final_test_window
                if final_start not in dates or final_end not in dates:
                    return None
                final_start_index = dates.index(final_start)
                final_end_index = dates.index(final_end)
                warmup_start_index = final_start_index - xaj.warmup_days
                if warmup_start_index < 0 or final_end_index < final_start_index:
                    return None
                slice_end = final_end_index + 1
                dates = dates[warmup_start_index:slice_end]
                values = values[warmup_start_index:slice_end]
                if baseline_values is not None:
                    baseline_values = baseline_values[warmup_start_index:slice_end]
                evaluated_start = final_start.isoformat()
                evaluated_end = final_end.isoformat()
                effective_warmup_days = xaj.warmup_days
            else:
                evaluated_start = (
                    dates[xaj.warmup_days].isoformat()
                    if len(dates) > xaj.warmup_days
                    else dates[0].isoformat()
                )
                evaluated_end = dates[-1].isoformat()
                effective_warmup_days = xaj.warmup_days

            comparison = build_comparison(
                kind="independent_test",
                dates=dates,
                observed=observed,
                warmup_days=effective_warmup_days,
                evaluated_window="final_test",
                baseline=(
                    [float(v) for v in baseline_values]
                    if baseline_values is not None
                    else None
                ),
                frozen=[float(v) for v in values],
                gate_status=gate_status,
                frozen_is_candidate=frozen_is_candidate,
                windows={
                    "final_test": f"{evaluated_start}..{evaluated_end}",
                    "warmup": (
                        f"{dates[0].isoformat()}.."
                        f"{dates[min(effective_warmup_days, len(dates)) - 1].isoformat()}"
                    ),
                },
            )
            if output_dir is not None:
                write_bundle(Path(output_dir), comparison, stem="test-hydrograph")
            return comparison
        except Exception:
            return None

    def _load_streamflow(self, snapshot_id: str) -> dict:
        path = self.snapshot_root / snapshot_id / "streamflow.csv"
        if not path.exists():
            matches = list(self.snapshot_root.rglob(f"{snapshot_id}/streamflow.csv"))
            if not matches:
                raise FileNotFoundError(path)
            path = matches[0]
        rows = {}
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                from datetime import date as date_cls

                key = date_cls.fromisoformat(row["date"])
                rows[key] = float(row["discharge_m3s"])
        return rows
