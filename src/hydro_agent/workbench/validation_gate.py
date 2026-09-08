from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from hydro_agent.evaluation.metrics import build_evaluation_bundle, mae, nse
from hydro_agent.execution.contracts import ExecutionPolicy


@dataclass(frozen=True)
class ValidationWindow:
    start: date
    end: date

    @property
    def issue_days(self) -> tuple[date, ...]:
        days = []
        cur = self.start
        while cur <= self.end:
            days.append(cur)
            cur += timedelta(days=1)
        return tuple(days)

    @property
    def calibration_issue(self) -> date:
        # Hold out the validation window; calibrate on the day before it starts.
        return self.start - timedelta(days=1)


def truth_from_source(flow_rows) -> dict[date, float]:
    return {row.valid_date: float(row.discharge_m3s) for row in flow_rows}


def collect_lead_series(
    *,
    forecasts,
    scheme_id: str,
    truth: dict[date, float],
) -> dict[int, tuple[list[float], list[float]]]:
    lead_obs: dict[int, list[float]] = {1: [], 2: [], 3: []}
    lead_sim: dict[int, list[float]] = {1: [], 2: [], 3: []}
    for forecast in forecasts:
        if forecast.scheme_id != scheme_id:
            continue
        issue_date = forecast.issue_time.date()
        values = forecast.lead_values_json
        for lead_key, value in values.items():
            lead = int(lead_key)
            target = issue_date + timedelta(days=lead)
            if target not in truth:
                continue
            lead_obs[lead].append(float(truth[target]))
            lead_sim[lead].append(float(value))
    return {lead: (lead_obs[lead], lead_sim[lead]) for lead in (1, 2, 3)}


def require_enough_pairs(series: dict[int, tuple[list[float], list[float]]]) -> None:
    for lead, (obs, _sim) in series.items():
        if len(obs) < 2:
            raise RuntimeError(f"validation window too short for lead-{lead} Gate metrics")


def diagnose_forecast_errors(
    *,
    truth: dict[date, float],
    lead_values: dict[int, float],
    issue_day: date,
) -> dict[str, Any]:
    """Lightweight hydrologic diagnosis from one issue's lead-1/2/3 vs observations."""
    obs = []
    sim = []
    for lead, value in sorted(lead_values.items()):
        target = issue_day + timedelta(days=int(lead))
        if target not in truth:
            continue
        obs.append(truth[target])
        sim.append(float(value))
    if len(obs) < 2:
        return {
            "hypothesis": "UNKNOWN",
            "phenomenon": "观测不足以诊断",
            "recommended_action": "A01_CHECK_DATA",
            "recommended_strategy_id": None,
            "metrics": {},
            "notes": ["need >=2 lead observations"],
        }
    err_mae = mae(obs, sim)
    try:
        err_nse = nse(obs, sim)
    except ValueError:
        err_nse = float("nan")
    peak_obs = max(obs)
    peak_sim = max(sim)
    under_peak = peak_sim < 0.85 * peak_obs
    over_peak = peak_sim > 1.15 * peak_obs
    mean_bias = (sum(sim) - sum(obs)) / max(sum(obs), 1e-9)
    notes = [
        f"mae={err_mae:.3f}",
        f"nse={err_nse:.3f}" if err_nse == err_nse else "nse=nan",
        f"peak_obs={peak_obs:.3f}",
        f"peak_sim={peak_sim:.3f}",
        f"mean_bias={mean_bias:.3f}",
    ]
    if under_peak and abs(mean_bias) > 0.1:
        return {
            "hypothesis": "MODEL",
            "phenomenon": "持续偏小/洪峰低估，优先怀疑产汇流参数系统偏差",
            "recommended_action": "A07_OPTIMIZE",
            "recommended_strategy_id": "xaj-peak-bias-v1",
            "metrics": {
                "mae": float(err_mae),
                "nse": float(err_nse) if err_nse == err_nse else 0.0,
                "mean_bias": float(mean_bias),
                "peak_ratio": float(peak_sim / peak_obs) if peak_obs else 0.0,
            },
            "notes": notes,
        }
    if over_peak:
        return {
            "hypothesis": "MODEL",
            "phenomenon": "洪峰偏高，建议局部细化参数而非全局重搜",
            "recommended_action": "A07_OPTIMIZE",
            "recommended_strategy_id": "xaj-local-refine-v1",
            "metrics": {
                "mae": float(err_mae),
                "nse": float(err_nse) if err_nse == err_nse else 0.0,
                "mean_bias": float(mean_bias),
                "peak_ratio": float(peak_sim / peak_obs) if peak_obs else 0.0,
            },
            "notes": notes,
        }
    if abs(mean_bias) < 0.05 and err_nse == err_nse and err_nse > 0.5:
        return {
            "hypothesis": "MODEL",
            "phenomenon": "整体偏差不大，可冻结进入回放评估",
            "recommended_action": "A10_FREEZE",
            "recommended_strategy_id": None,
            "metrics": {
                "mae": float(err_mae),
                "nse": float(err_nse),
                "mean_bias": float(mean_bias),
            },
            "notes": notes,
        }
    return {
        "hypothesis": "UNKNOWN",
        "phenomenon": "误差模式不清晰，先做有界再率定并独立验证",
        "recommended_action": "A07_OPTIMIZE",
        "recommended_strategy_id": "xaj-bounded-v1",
        "metrics": {
            "mae": float(err_mae),
            "nse": float(err_nse) if err_nse == err_nse else 0.0,
            "mean_bias": float(mean_bias),
        },
        "notes": notes,
    }


class RealValidationGate:
    """Run base/candidate forecasts on a held-out window and build Gate bundles."""

    def __init__(self, *, repository, forecast_service, source, policy: ExecutionPolicy, task_configs: dict):
        self.repository = repository
        self.forecast = forecast_service
        self.source = source
        self.policy = policy
        self.task_configs = task_configs

    def window_for(self, task_id: str) -> ValidationWindow:
        cfg = self.task_configs.get(task_id) or {}
        start = cfg.get("start_date") or "2020-04-29"
        end = cfg.get("end_date") or "2020-05-01"
        start_d = date.fromisoformat(start[:10]) if isinstance(start, str) else start
        end_d = date.fromisoformat(end[:10]) if isinstance(end, str) else end
        return ValidationWindow(start=start_d, end=end_d)

    def ensure_forecasts(self, task_id: str, scheme_id: str, window: ValidationWindow) -> None:
        for day in window.issue_days:
            issue = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            issue_iso = issue.isoformat().replace("+00:00", "Z")
            self.forecast.forecast(
                task_id=task_id,
                scheme_id=scheme_id,
                issue_time=issue_iso,
                policy=self.policy,
            )

    def bundles(self, task_id: str):
        schemes = self.repository.list_schemes(task_id)
        base = next((s for s in schemes if s.status == "base"), None)
        candidate = next((s for s in reversed(list(schemes)) if s.status == "candidate"), None)
        if base is None or candidate is None:
            raise RuntimeError("gate requires base and candidate schemes")
        window = self.window_for(task_id)
        self.ensure_forecasts(task_id, base.scheme_id, window)
        self.ensure_forecasts(task_id, candidate.scheme_id, window)
        truth = truth_from_source(self.source.flow_rows)
        forecasts = self.repository.list_forecasts(task_id)
        base_series = collect_lead_series(
            forecasts=forecasts, scheme_id=base.scheme_id, truth=truth
        )
        cand_series = collect_lead_series(
            forecasts=forecasts, scheme_id=candidate.scheme_id, truth=truth
        )
        require_enough_pairs(base_series)
        require_enough_pairs(cand_series)
        return (
            build_evaluation_bundle(base.scheme_id, base_series),
            build_evaluation_bundle(candidate.scheme_id, cand_series),
        )
