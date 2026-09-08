from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

from hydro_agent.evaluation.metrics import bias, kge, mae, nse
from hydro_agent.replay.contracts import ReplayEvaluation


class EvaluationService:
    def __init__(self, repository, *, snapshot_root: Path, observation_loader=None):
        self.repository = repository
        self.snapshot_root = Path(snapshot_root)
        self.observation_loader = observation_loader or self._load_streamflow

    def evaluate(self, task_id: str, observation_snapshot_id: str) -> ReplayEvaluation:
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
        return ReplayEvaluation(
            task_id=task_id,
            scheme_id=scheme.scheme_id,
            observation_snapshot_id=observation_snapshot_id,
            forecast_ids=tuple(row.forecast_id for row in forecasts),
            metrics=metrics,
            lead_metrics=lead_metrics,
            sample_counts=sample_counts,
            forcing_mode=task.forcing_mode,
            provenance=(scheme.config_json or {}).get("provenance") or {},
        )

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
