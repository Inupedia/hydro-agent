"""Continuous calibration-period evidence used before experiment selection.

This module is deliberately read-only: it simulates the current scheme on the
preregistered calibration window and summarizes multi-scale evidence. It never
reads development or final_test and never chooses continuous parameter values.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

import numpy as np

from hydro_agent.evaluation.evidence import HydrologicEvidenceBuilder
from hydro_agent.evaluation.evidence_summary import annual_stability_evidence
from hydro_agent.models.diagnosis_defaults import (
    composite_plan,
    peak_plan,
    resolve_model_id,
    timing_plan,
    water_balance_plan,
)
from hydro_agent.models.registry import default_model_registry


def build_calibration_evidence(
    *,
    source,
    scheme_config: dict[str, Any],
    calibration_start: date,
    calibration_end: date,
) -> dict[str, object]:
    if calibration_end < calibration_start:
        raise ValueError("calibration_end before calibration_start")
    warmup_days = int(scheme_config.get("warmup_days") or 1)
    series_start = calibration_start - timedelta(days=warmup_days)
    forcing_by_date = {row.valid_date: row for row in source.forcing_rows}
    required_dates = tuple(
        series_start + timedelta(days=index)
        for index in range((calibration_end - series_start).days + 1)
    )
    missing_forcing = [day for day in required_dates if day not in forcing_by_date]
    if missing_forcing:
        raise ValueError(
            f"calibration evidence forcing incomplete: missing={missing_forcing[0].isoformat()}"
        )

    model_id = str(scheme_config.get("model_id") or "xaj")
    plugin = default_model_registry().get(model_id)
    forcing = np.asarray(
        [
            [
                float(forcing_by_date[day].precipitation_mm_day),
                float(forcing_by_date[day].pet_mm_day),
            ]
            for day in required_dates
        ],
        dtype=float,
    )
    full_sim = plugin.simulate(
        scheme_config,
        dict(source.basin),
        forcing[:, None, :],
        include_warmup=True,
    )
    if len(full_sim) != len(required_dates):
        raise ValueError("calibration continuous simulation length mismatch")

    flow_by_date = {row.valid_date: row for row in source.flow_rows}
    dates = [day for day in required_dates if day >= calibration_start]
    offset = warmup_days
    simulated = [float(value) for value in full_sim[offset : offset + len(dates)]]
    observed: list[float | None] = []
    quality_mask: list[bool] = []
    for day in dates:
        row = flow_by_date.get(day)
        observed.append(float(row.discharge_m3s) if row is not None else None)
        quality_mask.append(bool(row is not None and row.eligible_for_scoring))

    bundle = HydrologicEvidenceBuilder().build(
        window="calibration",
        dates=dates,
        observed=observed,
        simulated=simulated,
        quality_mask=quality_mask,
    )
    payload = bundle.as_dict()
    payload["annual_stability"] = asdict(annual_stability_evidence(bundle))
    payload["provenance"] = {
        "calibration_start": calibration_start.isoformat(),
        "calibration_end": calibration_end.isoformat(),
        "warmup_days": warmup_days,
        "model_id": model_id,
        "development_accessed": False,
        "final_test_accessed": False,
    }
    return payload


def apply_calibration_evidence_to_diagnosis(
    rolling_diagnosis: dict[str, Any],
    calibration_evidence: dict[str, object],
    *,
    dc_bing_floor: float,
    water_balance_threshold: float = 10.0,
) -> dict[str, Any]:
    """Make full calibration evidence primary and rolling forecasts supplemental.

    ``dc_bing_floor`` is the normative GB/T DC 丙 threshold from Standards. It
    guides the next experiment hypothesis only; Campaign stopping remains owned
    by Campaign/ConvergencePolicy.
    """

    result = dict(rolling_diagnosis)
    provenance = calibration_evidence.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    model_id = resolve_model_id(result, provenance)
    result["model_id"] = model_id

    rolling_metrics = dict(result.get("metrics") or {})
    metrics = {f"rolling_{key}": float(value) for key, value in rolling_metrics.items()}
    overall = calibration_evidence.get("overall")
    overall = overall if isinstance(overall, dict) else {}
    overall_metrics = overall.get("metrics")
    overall_metrics = overall_metrics if isinstance(overall_metrics, dict) else {}
    for key, value in overall_metrics.items():
        if isinstance(value, (int, float)):
            metrics[f"calibration_{key}"] = float(value)
    for key in ("nse", "kge", "pbias_percent", "mae", "rmse", "peak_ratio"):
        value = overall_metrics.get(key)
        if isinstance(value, (int, float)):
            metrics[key] = float(value)
    peak_lag = overall_metrics.get("peak_timing_lag_steps")
    if isinstance(peak_lag, (int, float)):
        metrics["peak_timing_lag_days"] = float(peak_lag)

    quality = calibration_evidence.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    valid_count = int(quality.get("valid_count") or 0)
    if overall.get("status") != "available" or valid_count < 2:
        result.update(
            {
                "hypothesis": "DATA",
                "phenomenon": "完整率定期有效观测不足，不能设计可信参数实验",
                "recommended_action": "A01_CHECK_DATA",
                "recommended_strategy_id": None,
                "recommended_param_groups": None,
                "recommended_objective": None,
                "metrics": metrics,
            }
        )
    else:
        pbias = metrics.get("pbias_percent")
        peak_ratio = metrics.get("peak_ratio", 1.0)
        peak_timing = metrics.get("peak_timing_lag_days", 0.0)
        full_nse = metrics.get("nse")
        if pbias is not None and abs(pbias) >= water_balance_threshold:
            strategy, groups = water_balance_plan(model_id)
            phenomenon = (
                f"完整率定期 PBIAS={pbias:.1f}% 显示系统水量偏差，优先处理产流/交换参数"
                if model_id == "gr4j"
                else f"完整率定期 PBIAS={pbias:.1f}% 显示系统水量偏差，优先处理蒸散发/产流参数"
            )
            result.update(
                {
                    "hypothesis": "MODEL",
                    "phenomenon": phenomenon,
                    "recommended_action": "A05_OPTIMIZE",
                    "recommended_strategy_id": strategy,
                    "recommended_param_groups": groups,
                    "recommended_objective": "composite",
                }
            )
        elif abs(peak_timing) >= 1:
            strategy, groups = timing_plan(model_id)
            result.update(
                {
                    "hypothesis": "TIMING",
                    "phenomenon": f"完整率定期洪峰错位约 {peak_timing:.0f} 天，优先检查汇流响应",
                    "recommended_action": "A05_OPTIMIZE",
                    "recommended_strategy_id": strategy,
                    "recommended_param_groups": groups,
                    "recommended_objective": "composite",
                }
            )
        elif peak_ratio < 0.85 or peak_ratio > 1.15:
            strategy, groups = peak_plan(model_id)
            result.update(
                {
                    "hypothesis": "MODEL",
                    "phenomenon": f"完整率定期洪峰比={peak_ratio:.2f}，优先联合产流与汇流过程",
                    "recommended_action": "A05_OPTIMIZE",
                    "recommended_strategy_id": strategy,
                    "recommended_param_groups": groups,
                    "recommended_objective": "composite",
                }
            )
        elif full_nse is None or full_nse < dc_bing_floor:
            strategy, groups = composite_plan(model_id)
            result.update(
                {
                    "hypothesis": "MODEL",
                    "phenomenon": "完整率定期整体拟合不足，采用受约束综合率定",
                    "recommended_action": "A05_OPTIMIZE",
                    "recommended_strategy_id": strategy,
                    "recommended_param_groups": groups,
                    "recommended_objective": "composite",
                }
            )
        else:
            result.update(
                {
                    "hypothesis": "MODEL",
                    "phenomenon": "完整率定期多指标达到当前研究阈值，不继续无意义搜索",
                    "recommended_action": "A08_FREEZE",
                    "recommended_strategy_id": None,
                    "recommended_param_groups": None,
                    "recommended_objective": None,
                }
            )
        result["metrics"] = metrics

    notes = list(result.get("notes") or [])
    notes.extend(
        (
            "diagnosis_primary_evidence=continuous_calibration",
            "diagnosis_supplemental_evidence=rolling_predevelopment",
            "calibration_evidence_development_accessed=false",
            "calibration_evidence_final_test_accessed=false",
            f"calibration_valid_samples={valid_count}",
            f"model_id={model_id}",
        )
    )
    result["notes"] = notes
    result["calibration_evidence"] = calibration_evidence
    return result
