from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

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
        metrics = {
            key: float(sum(item[key] for item in lead_metrics.values()) / len(lead_metrics))
            for key in ("NSE", "KGE", "MAE", "Bias")
        }
        # Attach GB/T 22482 multi-metric report on concatenated leads.
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
                metrics.update(report.as_metrics_dict())
        except Exception as exc:  # noqa: BLE001
            gbt_payload = {"error": str(exc)}
        provenance = dict((scheme.config_json or {}).get("provenance") or {})
        if gbt_payload:
            provenance = {**provenance, "gbt_22482": gbt_payload}
        gate_status = self._latest_gate_status(task_id)
        frozen_is_candidate = gate_status == "ACCEPT"
        hydrograph = self._try_test_hydrograph(
            observation_snapshot_id,
            scheme,
            output_dir=output_dir,
            gate_status=gate_status,
            frozen_is_candidate=frozen_is_candidate,
        )
        return ReplayEvaluation(
            task_id=task_id,
            scheme_id=scheme.scheme_id,
            observation_snapshot_id=observation_snapshot_id,
            forecast_ids=tuple(row.forecast_id for row in forecasts),
            metrics=metrics,
            lead_metrics=lead_metrics,
            sample_counts=sample_counts,
            forcing_mode=task.forcing_mode,
            provenance=provenance,
            hydrograph=hydrograph,
        )

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
                [[float(row["precipitation_mm_day"]), float(row["pet_mm_day"])] for row in rows]
            )
            if len(dates) < xaj.warmup_days + 2:
                return None
            values = simulate(xaj, basin, array[:, None, :], include_warmup=True)
            observed = self.observation_loader(observation_snapshot_id)
            if not isinstance(observed, dict):
                return None
            start = (
                dates[xaj.warmup_days].isoformat()
                if len(dates) > xaj.warmup_days
                else dates[0].isoformat()
            )
            comparison = build_comparison(
                kind="independent_test",
                dates=dates,
                observed=observed,
                warmup_days=xaj.warmup_days,
                evaluated_window="test",
                frozen=[float(v) for v in values],
                gate_status=gate_status,
                frozen_is_candidate=frozen_is_candidate,
                windows={
                    "test": f"{start}..{dates[-1].isoformat()}",
                    "warmup": f"{dates[0].isoformat()}..{dates[min(xaj.warmup_days, len(dates)) - 1].isoformat()}",
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
            # Nested layout used by SnapshotBuilder under basin folders.
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
