from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from hydro_agent.api.i18n_zh import (
    action_zh,
    hypothesis_zh,
    phase_zh,
    scheme_status_zh,
    status_zh,
)
from hydro_agent.api.schemas import (
    AgentLogSummary,
    AgentRoundLogItem,
    CalibrationComparisonPoint,
    ForecastResult,
    ResultSummary,
    SchemeResult,
)

router = APIRouter(prefix="/api/tasks", tags=["results"])


def _story_zh(*, phase: str, scheme, gate, metrics, comparison, reports) -> str:
    parts = [f"任务已进入「{phase_zh(phase)}」阶段。"]
    if scheme is not None:
        parts.append(f"当前发布候选为{scheme_status_zh(scheme.status)}（{scheme.scheme_id}）。")
    if gate:
        gate_status = str(gate.get("status") or "")
        parts.append(f"率定结论：{status_zh(gate_status)}。")
        reasons = gate.get("reasons") or []
        if reasons:
            parts.append("原因：" + "；".join(str(r) for r in reasons[:3]) + "。")
    metric_bits = []
    for key in ("NSE", "KGE", "MAE", "Bias"):
        value = metrics.get(key)
        if value is not None:
            metric_bits.append(f"{key}={float(value):.3f}")
    if metric_bits:
        parts.append("独立评价指标：" + "，".join(metric_bits) + "。")
    if comparison:
        parts.append(f"发布页可对比 {len(comparison)} 个时段的率定后计算流量与实测流量。")
    if reports:
        parts.append("报告文件：" + "、".join(reports) + "。")
    return "".join(parts)


def _observed_by_date(deps, scheme_row) -> dict[str, float]:
    plan_id = (scheme_row.config_json or {}).get("model_plan_id")
    if not plan_id or deps.model_plans is None:
        return {}
    path = deps.model_plans.directory(str(plan_id)) / "case" / "model_inputs" / "observed.csv"
    if not path.is_file():
        return {}
    rows: dict[str, float] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                rows[str(row["time"])[:10]] = float(row["discharge"])
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def _comparison_series(deps, task_id: str, scheme_row) -> tuple[CalibrationComparisonPoint, ...]:
    """Build the product-facing calibrated-vs-observed curve.

    A published point uses the one-step-ahead value from the frozen/current scheme.
    This keeps a single unambiguous simulated value per target day. Initial/base
    simulation is optional and is only attached when the same target date exists.
    """

    observed = _observed_by_date(deps, scheme_row)
    if not observed:
        return ()
    all_forecasts = deps.repository.list_forecasts(task_id)
    calibrated = [row for row in all_forecasts if row.scheme_id == scheme_row.scheme_id]
    if not calibrated:
        return ()
    base_ids = {row.scheme_id for row in deps.repository.list_schemes(task_id=task_id, status="base")}
    base_forecasts = [row for row in all_forecasts if row.scheme_id in base_ids]

    def one_step(rows):
        values: dict[str, float] = {}
        for row in rows:
            raw = row.lead_values_json or {}
            value = raw.get("1", raw.get(1))
            if value is None:
                continue
            target = (row.issue_time.date() + timedelta(days=1)).isoformat()
            values[target] = float(value)
        return values

    calibrated_by_date = one_step(calibrated)
    initial_by_date = one_step(base_forecasts)
    points = []
    for day in sorted(set(observed) & set(calibrated_by_date)):
        points.append(
            CalibrationComparisonPoint(
                time=day,
                observed=observed[day],
                calibrated=calibrated_by_date[day],
                initial=initial_by_date.get(day),
            )
        )
    return tuple(points)


@router.get("/{task_id}/results", response_model=ResultSummary)
def get_results(task_id: str, request: Request) -> ResultSummary:
    deps = request.app.state.deps
    try:
        task = deps.repository.get_task(task_id)
        state = deps.repository.ensure_task_state(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    scheme_row = deps.repository.get_scheme(state.current_scheme_id)
    parameters = {
        str(k): float(v)
        for k, v in dict((scheme_row.config_json or {}).get("parameters") or {}).items()
    }
    provenance = dict((scheme_row.config_json or {}).get("provenance") or {})
    base_parameters: dict[str, float] = {}
    source_scheme_id = provenance.get("source_scheme_id") or provenance.get("base_scheme_id")
    if isinstance(source_scheme_id, str) and source_scheme_id:
        try:
            base_row = deps.repository.get_scheme(source_scheme_id)
            base_parameters = {
                str(k): float(v)
                for k, v in dict((base_row.config_json or {}).get("parameters") or {}).items()
            }
        except KeyError:
            base_parameters = {}
    if not base_parameters:
        for row in deps.repository.list_schemes(task_id=task_id, status="base"):
            base_parameters = {
                str(k): float(v)
                for k, v in dict((row.config_json or {}).get("parameters") or {}).items()
            }
            break
    parameter_delta = {
        key: float(parameters[key]) - float(base_parameters[key])
        for key in parameters
        if key in base_parameters and abs(float(parameters[key]) - float(base_parameters[key])) > 1e-12
    }
    scheme = SchemeResult(
        scheme_id=scheme_row.scheme_id,
        status=scheme_row.status,
        content_hash=scheme_row.content_hash,
        model_id=scheme_row.model_id,
        provenance=provenance,
        parameters=parameters,
        base_parameters=base_parameters,
        parameter_delta=parameter_delta,
    )
    forecasts = tuple(
        ForecastResult(
            forecast_id=row.forecast_id,
            scheme_id=row.scheme_id,
            issue_time=row.issue_time,
            lead_values={int(k): float(v) for k, v in row.lead_values_json.items()},
            unit=row.unit,
        )
        for row in deps.repository.list_forecasts(task_id)
    )
    comparison = _comparison_series(deps, task_id, scheme_row)

    gate = None
    diagnosis = None
    optimize = None
    evidence_rows = deps.repository.list_evidence(task_id)
    for row in reversed(evidence_rows):
        if gate is None and row.action == "A08_GATE":
            gates = dict(row.gates_json or {})
            reason_codes = str(gates.get("reasons") or "")
            gate = {
                **gates,
                "status": row.status,
                "reasons": list(row.observations_json or []),
                "reason_codes": [c for c in reason_codes.split(",") if c],
                "metrics": dict(row.metrics_json or {}),
            }
        if diagnosis is None and row.action == "A06_DIAGNOSE":
            diagnosis = {
                "observations": list(row.observations_json or []),
                "metrics": dict(row.metrics_json or {}),
                **dict(row.gates_json or {}),
            }
        if optimize is None and row.action == "A07_OPTIMIZE":
            optimize = {
                "observations": list(row.observations_json or []),
                "metrics": dict(row.metrics_json or {}),
                **dict(row.gates_json or {}),
            }
        if gate is not None and diagnosis is not None and optimize is not None:
            break

    metrics: dict[str, float | None] = {
        key: deps.metrics_by_task.get(task_id, {}).get(key) for key in ("NSE", "KGE", "MAE", "Bias")
    }
    comparison_scope = "unknown"
    for row in reversed(evidence_rows):
        if row.action == "A12_EVALUATE_REPORT" and row.metrics_json:
            metrics = {
                k: float(row.metrics_json[k]) if k in row.metrics_json else None
                for k in ("NSE", "KGE", "MAE", "Bias")
            }
            comparison_scope = "final_holdout"
            break

    report_artifacts = deps.report_artifacts.get(task_id, ())
    if not report_artifacts:
        for row in reversed(evidence_rows):
            if row.action == "A12_EVALUATE_REPORT" and row.artifact_ids_json:
                report_artifacts = tuple(row.artifact_ids_json)
                break
    costs: dict[str, float] = {}
    for row in deps.repository.list_forecasts(task_id):
        try:
            cost = deps.repository.get_cost(row.action_run_id)
            costs[row.action_run_id] = float(cost.wall_time_seconds)
        except KeyError:
            continue
    run_status = "completed" if task.phase == "E" and not state.needs_follow_up else task.phase
    return ResultSummary(
        task_id=task_id,
        phase=task.phase,  # type: ignore[arg-type]
        scheme=scheme,
        forecasts=forecasts,
        comparison=comparison,
        comparison_scope=comparison_scope,  # type: ignore[arg-type]
        metrics=metrics,
        gate=gate,
        diagnosis=diagnosis,
        optimize=optimize,
        report_artifacts=report_artifacts,
        costs=costs,
        story_zh=_story_zh(
            phase=task.phase,
            scheme=scheme,
            gate=gate,
            metrics=metrics,
            comparison=comparison,
            reports=report_artifacts,
        ),
        phase_zh=phase_zh(task.phase),
        status_zh=status_zh(run_status if run_status != task.phase else "idle"),
    )


@router.get("/{task_id}/agent-log", response_model=AgentLogSummary)
def get_agent_log(task_id: str, request: Request) -> AgentLogSummary:
    deps = request.app.state.deps
    try:
        deps.repository.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    rows = deps.list_agent_round_logs(task_id)
    if not rows:
        decisions = deps.repository.list_agent_decisions(task_id)
        evidence = deps.repository.list_evidence(task_id)
        by_action = {}
        for item in evidence:
            by_action.setdefault(item.action, []).append(item)
        for decision in decisions:
            bucket = by_action.get(decision.action) or []
            ev = bucket.pop(0) if bucket else None
            rows.append(
                {
                    "round_number": decision.round_number,
                    "occurred_at": decision.created_at.isoformat()
                    if getattr(decision, "created_at", None)
                    else None,
                    "action": decision.action,
                    "hypothesis": decision.hypothesis,
                    "strategy_id": decision.strategy_id,
                    "rationale_summary": decision.rationale_summary,
                    "llm_output": decision.rationale_summary,
                    "input_summary_zh": f"第 {decision.round_number} 轮决策（仅存档摘要）",
                    "input_world_state": {},
                    "tool_status": ev.status if ev else None,
                    "tool_observations": list(ev.observations_json or []) if ev else [],
                    "tool_metrics": dict(ev.metrics_json or {}) if ev else {},
                    "error": None,
                }
            )
    rounds = []
    for row in rows:
        action = row.get("action")
        tool_status = row.get("tool_status")
        rounds.append(
            AgentRoundLogItem(
                round_number=int(row.get("round_number") or 0),
                occurred_at=row.get("occurred_at"),
                action=action,
                action_zh=action_zh(action),
                hypothesis=row.get("hypothesis"),
                hypothesis_zh=hypothesis_zh(row.get("hypothesis")),
                strategy_id=row.get("strategy_id"),
                rationale_summary=str(row.get("rationale_summary") or ""),
                llm_output=str(row.get("llm_output") or ""),
                input_summary_zh=str(row.get("input_summary_zh") or ""),
                judgment_zh=str(row.get("judgment_zh") or ""),
                input_world_state=dict(row.get("input_world_state") or {}),
                tool_status=tool_status,
                tool_status_zh=status_zh(tool_status),
                tool_observations=tuple(row.get("tool_observations") or ()),
                tool_metrics={str(k): float(v) for k, v in dict(row.get("tool_metrics") or {}).items()},
                error=row.get("error"),
            )
        )
    return AgentLogSummary(task_id=task_id, rounds=tuple(rounds))


@router.get("/{task_id}/forecasts", response_model=list[ForecastResult])
def get_forecasts(task_id: str, request: Request) -> list[ForecastResult]:
    return list(get_results(task_id, request).forecasts)


@router.get("/{task_id}/report/{artifact_name}")
def get_report_artifact(task_id: str, artifact_name: str, request: Request):
    deps = request.app.state.deps
    if artifact_name not in {"report.json", "report.md", "agent-log.jsonl"}:
        raise HTTPException(status_code=404, detail="artifact not found")
    root = deps.report_root
    if not root:
        raise HTTPException(status_code=404, detail="report root not configured")
    path = Path(root) / task_id / artifact_name
    if not path.exists():
        path = Path(root) / artifact_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path)
