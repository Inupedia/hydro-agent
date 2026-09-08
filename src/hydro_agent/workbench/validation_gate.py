from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from hydro_agent.agent.contracts import ActionCode
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
    window: ValidationWindow | None = None,
) -> dict[int, tuple[list[float], list[float]]]:
    lead_obs: dict[int, list[float]] = {1: [], 2: [], 3: []}
    lead_sim: dict[int, list[float]] = {1: [], 2: [], 3: []}
    for forecast in forecasts:
        if forecast.scheme_id != scheme_id:
            continue
        issue_date = forecast.issue_time.date()
        if window is not None and (issue_date < window.start or issue_date > window.end):
            continue
        values = forecast.lead_values_json
        for lead_key, value in values.items():
            lead = int(lead_key)
            if lead not in lead_obs:
                continue
            target = issue_date + timedelta(days=lead)
            if target not in truth:
                continue
            lead_obs[lead].append(float(truth[target]))
            lead_sim[lead].append(float(value))
    return {lead: (lead_obs[lead], lead_sim[lead]) for lead in (1, 2, 3)}


def collect_aligned_lead_series(
    *,
    forecasts,
    base_scheme_id: str,
    candidate_scheme_id: str,
    truth: dict[date, float],
    window: ValidationWindow,
) -> tuple[dict[int, tuple[list[float], list[float]]], dict[int, tuple[list[float], list[float]]]]:
    """Build base/candidate series on identical (issue_day, lead, observation) samples."""
    by_scheme_issue: dict[tuple[str, date], Any] = {}
    for forecast in forecasts:
        if forecast.scheme_id not in (base_scheme_id, candidate_scheme_id):
            continue
        issue_date = forecast.issue_time.date()
        if issue_date < window.start or issue_date > window.end:
            continue
        key = (forecast.scheme_id, issue_date)
        # Prefer the lexicographically last forecast_id only as a last resort; Gate
        # should normally have one forecast per (scheme, issue).
        prev = by_scheme_issue.get(key)
        if prev is None or str(forecast.forecast_id) >= str(prev.forecast_id):
            by_scheme_issue[key] = forecast

    base_obs: dict[int, list[float]] = {1: [], 2: [], 3: []}
    base_sim: dict[int, list[float]] = {1: [], 2: [], 3: []}
    cand_obs: dict[int, list[float]] = {1: [], 2: [], 3: []}
    cand_sim: dict[int, list[float]] = {1: [], 2: [], 3: []}

    for day in window.issue_days:
        base_f = by_scheme_issue.get((base_scheme_id, day))
        cand_f = by_scheme_issue.get((candidate_scheme_id, day))
        if base_f is None or cand_f is None:
            continue
        for lead in (1, 2, 3):
            target = day + timedelta(days=lead)
            if target not in truth:
                continue
            b_key = str(lead)
            c_key = str(lead)
            if b_key not in base_f.lead_values_json or c_key not in cand_f.lead_values_json:
                continue
            obs = float(truth[target])
            base_obs[lead].append(obs)
            cand_obs[lead].append(obs)
            base_sim[lead].append(float(base_f.lead_values_json[b_key]))
            cand_sim[lead].append(float(cand_f.lead_values_json[c_key]))

    return (
        {lead: (base_obs[lead], base_sim[lead]) for lead in (1, 2, 3)},
        {lead: (cand_obs[lead], cand_sim[lead]) for lead in (1, 2, 3)},
    )


def require_enough_pairs(series: dict[int, tuple[list[float], list[float]]]) -> None:
    for lead, (obs, _sim) in series.items():
        if len(obs) < 2:
            raise RuntimeError(f"validation window too short for lead-{lead} Gate metrics")


def resolve_gate_scheme_ids(repository, task_id: str) -> tuple[str, str]:
    """Bind Gate to current scheme vs the candidate from the latest A07 optimize."""
    state = repository.ensure_task_state(task_id)
    base_scheme_id = state.current_scheme_id
    if not base_scheme_id:
        raise RuntimeError("gate requires a current scheme")

    candidate_scheme_id: str | None = None
    optimize_base_id: str | None = None
    for row in reversed(repository.list_evidence(task_id)):
        if row.action != ActionCode.A07_OPTIMIZE.value:
            continue
        gates = dict(row.gates_json or {})
        candidate_scheme_id = gates.get("candidate_scheme_id") or None
        optimize_base_id = gates.get("base_scheme_id") or None
        if not candidate_scheme_id:
            for obs in row.observations_json or ():
                if str(obs).startswith("candidate_scheme_id="):
                    candidate_scheme_id = str(obs).split("=", 1)[1]
                    break
        break

    if not candidate_scheme_id:
        raise RuntimeError("gate requires a candidate from the latest A07_OPTIMIZE")

    if candidate_scheme_id == base_scheme_id:
        # Should not happen before resolve; fall back to provenance / optimize base.
        try:
            scheme = repository.get_scheme(candidate_scheme_id)
            provenance = dict((scheme.config_json or {}).get("provenance") or {})
            base_scheme_id = str(
                provenance.get("base_scheme_id") or optimize_base_id or base_scheme_id
            )
        except KeyError:
            if optimize_base_id:
                base_scheme_id = optimize_base_id

    if candidate_scheme_id == base_scheme_id:
        raise RuntimeError("gate candidate equals baseline scheme")
    return base_scheme_id, candidate_scheme_id


def latest_candidate_scheme_id(repository, task_id: str) -> str | None:
    for row in reversed(repository.list_evidence(task_id)):
        if row.action != ActionCode.A07_OPTIMIZE.value:
            continue
        gates = dict(row.gates_json or {})
        candidate = gates.get("candidate_scheme_id")
        if candidate:
            return str(candidate)
        for obs in row.observations_json or ():
            if str(obs).startswith("candidate_scheme_id="):
                return str(obs).split("=", 1)[1]
    return None


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
        base_scheme_id, candidate_scheme_id = resolve_gate_scheme_ids(self.repository, task_id)
        window = self.window_for(task_id)
        self.ensure_forecasts(task_id, base_scheme_id, window)
        self.ensure_forecasts(task_id, candidate_scheme_id, window)
        truth = truth_from_source(self.source.flow_rows)
        forecasts = self.repository.list_forecasts(task_id)
        base_series, cand_series = collect_aligned_lead_series(
            forecasts=forecasts,
            base_scheme_id=base_scheme_id,
            candidate_scheme_id=candidate_scheme_id,
            truth=truth,
            window=window,
        )
        require_enough_pairs(base_series)
        require_enough_pairs(cand_series)
        return (
            build_evaluation_bundle(base_scheme_id, base_series),
            build_evaluation_bundle(candidate_scheme_id, cand_series),
        )
