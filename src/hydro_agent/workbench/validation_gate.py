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
    nse_good_enough: float | None = None,
) -> dict[str, Any]:
    """Lightweight hydrologic diagnosis from one issue's lead-1/2/3 vs observations."""
    from hydro_agent.skills import DEFAULT_NSE_GOOD_ENOUGH

    threshold = (
        float(nse_good_enough)
        if nse_good_enough is not None
        else DEFAULT_NSE_GOOD_ENOUGH
    )
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
            "recommended_param_groups": None,
            "recommended_objective": None,
            "hypotheses": [
                {
                    "id": "UNKNOWN",
                    "strength": 1.0,
                    "phenomenon": "观测不足以诊断",
                    "suggested_action": "A01_CHECK_DATA",
                    "suggested_strategy_id": None,
                    "suggested_param_groups": None,
                    "suggested_objective": None,
                }
            ],
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
    peak_ratio = float(peak_sim / peak_obs) if peak_obs else 0.0
    peak_obs_i = int(max(range(len(obs)), key=lambda i: obs[i]))
    peak_sim_i = int(max(range(len(sim)), key=lambda i: sim[i]))
    peak_timing_lag_leads = peak_sim_i - peak_obs_i
    notes = [
        f"mae={err_mae:.3f}",
        f"nse={err_nse:.3f}" if err_nse == err_nse else "nse=nan",
        f"peak_obs={peak_obs:.3f}",
        f"peak_sim={peak_sim:.3f}",
        f"mean_bias={mean_bias:.3f}",
        f"peak_timing_lag_leads={peak_timing_lag_leads}",
    ]
    metrics = {
        "mae": float(err_mae),
        "nse": float(err_nse) if err_nse == err_nse else 0.0,
        "mean_bias": float(mean_bias),
        "peak_ratio": peak_ratio,
        "peak_timing_lag_leads": float(peak_timing_lag_leads),
    }
    gbt_meets = False
    try:
        from hydro_agent.evaluation.gbt22482 import (
            GbtAccuracyConfig,
            HydroSeries,
            build_gbt_accuracy_report,
        )

        gbt = build_gbt_accuracy_report(
            HydroSeries(obs=tuple(float(x) for x in obs), sim=tuple(float(x) for x in sim)),
            GbtAccuracyConfig(min_scheme_grade="丙", grade_dc_bing=threshold),
        )
        metrics["DC"] = float(gbt.dc) if gbt.dc is not None else 0.0
        metrics["QR"] = float(gbt.accuracy_rate) if gbt.accuracy_rate is not None else 0.0
        metrics["scheme_grade_rank"] = float(
            {"不合格": 0, "丙": 1, "乙": 2, "甲": 3}.get(gbt.scheme_grade, 0)
        )
        notes.append(gbt.summary)
        gbt_meets = bool(gbt.meets_min_grade)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"gbt_accuracy_unavailable={exc}")

    hypotheses: list[dict[str, Any]] = []

    if abs(peak_timing_lag_leads) >= 1 and not under_peak:
        hypotheses.append(
            {
                "id": "TIMING",
                "strength": 0.78,
                "phenomenon": (
                    f"峰现时差约 {peak_timing_lag_leads} 个 lead，建议检查汇流/滞后参数（GB/T 峰现）"
                ),
                "suggested_action": "A07_OPTIMIZE",
                "suggested_strategy_id": "xaj-local-refine-v1",
                "suggested_param_groups": ["routing"],
                "suggested_objective": "nse",
            }
        )

    if under_peak and abs(mean_bias) > 0.1:
        hypotheses.append(
            {
                "id": "MODEL",
                "strength": 0.85,
                "phenomenon": "持续偏小/洪峰低估，优先怀疑产汇流参数系统偏差",
                "suggested_action": "A07_OPTIMIZE",
                "suggested_strategy_id": "xaj-peak-bias-v1",
                "suggested_param_groups": ["runoff", "routing"],
                "suggested_objective": "composite",
            }
        )
        hypotheses.append(
            {
                "id": "FORCING",
                "strength": 0.35,
                "phenomenon": "系统性偏低也可能来自降水强迫偏弱，建议复核资料",
                "suggested_action": "A01_CHECK_DATA",
                "suggested_strategy_id": None,
                "suggested_param_groups": None,
                "suggested_objective": None,
            }
        )
        hypotheses.append(
            {
                "id": "STATE",
                "strength": 0.25,
                "phenomenon": "初始土壤含水量偏低也会压低洪峰，可在预算允许时重建状态",
                "suggested_action": "A03_VALIDATE_SCHEME",
                "suggested_strategy_id": None,
                "suggested_param_groups": None,
                "suggested_objective": None,
            }
        )
    elif over_peak:
        hypotheses.append(
            {
                "id": "MODEL",
                "strength": 0.8,
                "phenomenon": "洪峰偏高，建议局部细化参数而非全局重搜",
                "suggested_action": "A07_OPTIMIZE",
                "suggested_strategy_id": "xaj-local-refine-v1",
                "suggested_param_groups": ["runoff", "routing"],
                "suggested_objective": "nse",
            }
        )
        hypotheses.append(
            {
                "id": "FORCING",
                "strength": 0.3,
                "phenomenon": "局部强降水高估也可能抬高峰值",
                "suggested_action": "A01_CHECK_DATA",
                "suggested_strategy_id": None,
                "suggested_param_groups": None,
                "suggested_objective": None,
            }
        )
    elif gbt_meets or (abs(mean_bias) < 0.05 and err_nse == err_nse and err_nse >= threshold):
        hypotheses.append(
            {
                "id": "MODEL",
                "strength": 0.7,
                "phenomenon": (
                    f"GB/T 方案等级已达丙或 NSE≥{threshold}，可冻结进入回放评估"
                    if gbt_meets
                    else f"整体偏差不大且 NSE≥{threshold}，可冻结进入回放评估"
                ),
                "suggested_action": "A10_FREEZE",
                "suggested_strategy_id": None,
                "suggested_param_groups": None,
                "suggested_objective": None,
            }
        )
    else:
        hypotheses.append(
            {
                "id": "MODEL",
                "strength": 0.55,
                "phenomenon": "误差模式不清晰，建议有界再率定并独立验证",
                "suggested_action": "A07_OPTIMIZE",
                "suggested_strategy_id": "xaj-bounded-v1",
                "suggested_param_groups": ["evap", "runoff", "routing"],
                "suggested_objective": "nse",
            }
        )
        hypotheses.append(
            {
                "id": "UNKNOWN",
                "strength": 0.4,
                "phenomenon": "也可能是资料或事件特殊性，先复核观测覆盖",
                "suggested_action": "A01_CHECK_DATA",
                "suggested_strategy_id": None,
                "suggested_param_groups": None,
                "suggested_objective": None,
            }
        )

    primary = max(hypotheses, key=lambda item: float(item["strength"]))
    return {
        "hypothesis": primary["id"],
        "phenomenon": primary["phenomenon"],
        "recommended_action": primary["suggested_action"],
        "recommended_strategy_id": primary.get("suggested_strategy_id"),
        "recommended_param_groups": primary.get("suggested_param_groups"),
        "recommended_objective": primary.get("suggested_objective"),
        "hypotheses": hypotheses,
        "metrics": metrics,
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
        from hydro_agent.evaluation.gbt22482 import series_from_lead_lists

        area = None
        scheme = self.repository.get_scheme(candidate_scheme_id)
        cfg = dict(scheme.config_json or {})
        # Prefer plan area when present on scheme routing/metadata.
        for key in ("area_km2", "basin_area_km2"):
            if cfg.get(key) is not None:
                try:
                    area = float(cfg[key])
                except (TypeError, ValueError):
                    pass
        hydro = series_from_lead_lists(cand_series, area_km2=area)
        return (
            build_evaluation_bundle(base_scheme_id, base_series),
            build_evaluation_bundle(candidate_scheme_id, cand_series),
            hydro,
        )
