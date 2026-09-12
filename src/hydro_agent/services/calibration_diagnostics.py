"""Leakage-safe calibration diagnostics built only from pre-validation evidence."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from hydro_agent.evaluation.metrics import (
    bias,
    high_flow_mae,
    kge,
    mae,
    nse,
    pbias_percent,
    rmse,
)
from hydro_agent.knowledge.basin_priors import derive_basin_hydro_profile
from hydro_agent.knowledge.expert import ExpertKnowledgeRepository


def _safe(metric, obs: list[float], sim: list[float]) -> float | None:
    try:
        return float(metric(obs, sim))
    except (TypeError, ValueError):
        return None


def _truth(flow_rows) -> dict[date, float]:
    return {row.valid_date: float(row.discharge_m3s) for row in flow_rows}


def _latest_by_issue(forecasts, scheme_id: str) -> dict[date, Any]:
    out: dict[date, Any] = {}
    for row in forecasts:
        if row.scheme_id != scheme_id:
            continue
        issue = row.issue_time.date()
        prev = out.get(issue)
        if prev is None or str(row.forecast_id) >= str(prev.forecast_id):
            out[issue] = row
    return out


def diagnose_prevalidation_window(
    *,
    repository,
    forecast_service,
    source,
    policy,
    task_id: str,
    scheme_id: str,
    validation_start: date,
    nse_good_enough: float,
    lookback_issue_days: int = 10,
    expert_knowledge: ExpertKnowledgeRepository | None = None,
) -> dict[str, Any]:
    """Diagnose with issue/target dates strictly before the validation window.

    The latest diagnostic issue is ``validation_start - 4 days`` so lead-3 truth
    ends on ``validation_start - 1 day``. This keeps held-out validation
    observations out of Agent planning.
    """

    if lookback_issue_days < 4:
        raise ValueError("lookback_issue_days must be >= 4")

    latest_issue = validation_start - timedelta(days=4)
    first_issue = latest_issue - timedelta(days=lookback_issue_days - 1)
    issue_days = tuple(first_issue + timedelta(days=i) for i in range(lookback_issue_days))

    existing = _latest_by_issue(repository.list_forecasts(task_id), scheme_id)
    for day in issue_days:
        if day in existing:
            continue
        issue = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        forecast_service.forecast(
            task_id=task_id,
            scheme_id=scheme_id,
            issue_time=issue.isoformat().replace("+00:00", "Z"),
            policy=policy,
        )
    forecasts = _latest_by_issue(repository.list_forecasts(task_id), scheme_id)
    truth = _truth(source.flow_rows)

    all_obs: list[float] = []
    all_sim: list[float] = []
    lead_metrics: dict[str, float] = {}
    lead1_obs: list[float] = []
    lead1_sim: list[float] = []

    for lead in (1, 2, 3):
        obs: list[float] = []
        sim: list[float] = []
        for issue_day in issue_days:
            row = forecasts.get(issue_day)
            if row is None:
                continue
            target = issue_day + timedelta(days=lead)
            if target >= validation_start or target not in truth:
                continue
            key = str(lead)
            if key not in row.lead_values_json:
                continue
            obs.append(float(truth[target]))
            sim.append(float(row.lead_values_json[key]))
        if len(obs) >= 2:
            lead_nse = _safe(nse, obs, sim)
            if lead_nse is not None:
                lead_metrics[f"lead_{lead}_nse"] = lead_nse
            lead_metrics[f"lead_{lead}_mae"] = float(mae(obs, sim))
            all_obs.extend(obs)
            all_sim.extend(sim)
            if lead == 1:
                lead1_obs, lead1_sim = obs, sim

    if len(all_obs) < 6:
        return {
            "hypothesis": "DATA",
            "phenomenon": "率定期历史预报/观测不足，不能形成无泄漏诊断",
            "recommended_action": "A01_CHECK_DATA",
            "recommended_strategy_id": None,
            "recommended_param_groups": None,
            "recommended_objective": None,
            "hypotheses": [],
            "metrics": {"diagnostic_pairs": float(len(all_obs))},
            "notes": [
                f"diagnostic_window={first_issue.isoformat()}..{latest_issue.isoformat()}",
                f"validation_starts={validation_start.isoformat()}",
                "diagnostic_truth_strictly_precedes_validation=true",
            ],
        }

    metrics: dict[str, float] = {
        "diagnostic_pairs": float(len(all_obs)),
        "mae": float(mae(all_obs, all_sim)),
        "rmse": float(rmse(all_obs, all_sim)),
        "bias": float(bias(all_obs, all_sim)),
        "pbias_percent": float(pbias_percent(all_obs, all_sim)),
        **lead_metrics,
    }
    overall_nse = _safe(nse, all_obs, all_sim)
    overall_kge = _safe(kge, all_obs, all_sim)
    if overall_nse is not None:
        metrics["nse"] = overall_nse
    if overall_kge is not None:
        metrics["kge"] = overall_kge
    high_mae = _safe(high_flow_mae, all_obs, all_sim)
    if high_mae is not None:
        metrics["high_flow_mae"] = high_mae

    peak_ratio = 1.0
    peak_lag = 0
    if lead1_obs and lead1_sim:
        peak_obs = max(lead1_obs)
        peak_sim = max(lead1_sim)
        if peak_obs:
            peak_ratio = float(peak_sim / peak_obs)
        peak_obs_i = max(range(len(lead1_obs)), key=lambda i: lead1_obs[i])
        peak_sim_i = max(range(len(lead1_sim)), key=lambda i: lead1_sim[i])
        peak_lag = int(peak_sim_i - peak_obs_i)
        metrics["peak_ratio"] = peak_ratio
        metrics["peak_timing_lag_days"] = float(peak_lag)

    basin_raw = dict(getattr(source, "basin", {}) or {})
    area_raw = basin_raw.get("area_km2")
    basin_attributes: dict[str, Any] = {}
    if isinstance(area_raw, (int, float)) and float(area_raw) > 0:
        profile = derive_basin_hydro_profile(
            forcing_rows=source.forcing_rows,
            flow_rows=source.flow_rows,
            area_km2=float(area_raw),
            before_date=validation_start,
        )
        basin_attributes = profile.model_dump(exclude_none=True)

    expert = expert_knowledge or ExpertKnowledgeRepository()
    water_balance_rule = expert.rule("expert.water_balance_first")
    if water_balance_rule.threshold is None:
        raise ValueError("expert.water_balance_first requires a threshold")
    water_balance_threshold = float(water_balance_rule.threshold)

    pbias = metrics["pbias_percent"]
    hypotheses: list[dict[str, Any]] = []

    # Expert-prior ordering: fix water balance before fine-tuning hydrograph shape.
    if abs(pbias) >= water_balance_threshold:
        hypotheses.append(
            {
                "id": "MODEL",
                "strength": 0.9,
                "phenomenon": (
                    f"率定期水量偏差 PBIAS={pbias:.1f}% 达到专家先验阈值 "
                    f"±{water_balance_threshold:g}%，优先处理蒸散发/产流，不先精调汇流"
                ),
                "suggested_action": "A07_OPTIMIZE",
                "suggested_strategy_id": "xaj-water-balance-v1",
                "suggested_param_groups": ["evap", "runoff"],
                "suggested_objective": "composite",
                "knowledge_refs": [water_balance_rule.rule_id],
            }
        )
    elif abs(peak_lag) >= 1:
        hypotheses.append(
            {
                "id": "TIMING",
                "strength": 0.82,
                "phenomenon": f"率定期 lead-1 洪峰错位约 {peak_lag} 天，优先检查汇流响应",
                "suggested_action": "A07_OPTIMIZE",
                "suggested_strategy_id": "xaj-routing-refine-v1",
                "suggested_param_groups": ["routing"],
                "suggested_objective": "composite",
            }
        )
    elif peak_ratio < 0.85 or peak_ratio > 1.15:
        hypotheses.append(
            {
                "id": "MODEL",
                "strength": 0.78,
                "phenomenon": f"率定期洪峰比={peak_ratio:.2f}，优先联合产流与汇流过程",
                "suggested_action": "A07_OPTIMIZE",
                "suggested_strategy_id": "xaj-peak-bias-v1",
                "suggested_param_groups": ["runoff", "routing"],
                "suggested_objective": "composite",
            }
        )
    elif overall_nse is None or overall_nse < nse_good_enough:
        hypotheses.append(
            {
                "id": "MODEL",
                "strength": 0.62,
                "phenomenon": "水量与峰值无单一主导问题，但整体拟合不足，采用受约束综合率定",
                "suggested_action": "A07_OPTIMIZE",
                "suggested_strategy_id": "xaj-hydro-composite-v1",
                "suggested_param_groups": ["evap", "runoff", "routing"],
                "suggested_objective": "composite",
            }
        )
    else:
        hypotheses.append(
            {
                "id": "MODEL",
                "strength": 0.75,
                "phenomenon": "率定期多指标已达到当前研究阈值，不继续无意义调参",
                "suggested_action": "A10_FREEZE",
                "suggested_strategy_id": None,
                "suggested_param_groups": None,
                "suggested_objective": None,
            }
        )

    primary = hypotheses[0]
    notes = [
        f"diagnostic_window={first_issue.isoformat()}..{latest_issue.isoformat()}",
        f"diagnostic_target_end={(validation_start - timedelta(days=1)).isoformat()}",
        f"validation_starts={validation_start.isoformat()}",
        "diagnostic_truth_strictly_precedes_validation=true",
        "hydrologist_order=water_balance->peak_timing->peak_magnitude->overall_skill",
        f"expert_prior={water_balance_rule.rule_id}",
    ]
    if basin_attributes:
        notes.append(
            "basin_attributes_json="
            + json.dumps(basin_attributes, ensure_ascii=False, sort_keys=True)
        )
        notes.append("basin_profile_strictly_precedes_validation=true")

    return {
        "hypothesis": primary["id"],
        "phenomenon": primary["phenomenon"],
        "recommended_action": primary["suggested_action"],
        "recommended_strategy_id": primary.get("suggested_strategy_id"),
        "recommended_param_groups": primary.get("suggested_param_groups"),
        "recommended_objective": primary.get("suggested_objective"),
        "hypotheses": hypotheses,
        "metrics": metrics,
        "basin_attributes": basin_attributes,
        "notes": notes,
    }
