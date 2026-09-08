from __future__ import annotations

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
    ForecastResult,
    ResultSummary,
    SchemeResult,
)

router = APIRouter(prefix="/api/tasks", tags=["results"])


def _story_zh(*, phase: str, scheme, gate, metrics, forecasts, reports) -> str:
    parts = [f"任务已进入「{phase_zh(phase)}」阶段。"]
    if scheme is not None:
        parts.append(
            f"当前方案为{scheme_status_zh(scheme.status)}（{scheme.scheme_id}）。"
        )
    if gate:
        gate_status = str(gate.get("status") or "")
        parts.append(f"Gate 结论：{status_zh(gate_status)}。")
        reasons = gate.get("reasons") or []
        if reasons:
            parts.append("原因：" + "；".join(str(r) for r in reasons[:3]) + "。")
    if any(v is not None for v in metrics.values()):
        metric_bits = []
        for key in ("NSE", "KGE", "MAE", "Bias"):
            value = metrics.get(key)
            if value is None:
                continue
            metric_bits.append(f"{key}={float(value):.3f}")
        if metric_bits:
            parts.append("评估指标：" + "，".join(metric_bits) + "。")
    if forecasts:
        parts.append(f"共生成 {len(forecasts)} 条预报记录。")
    if reports:
        parts.append("报告文件：" + "、".join(reports) + "。")
    parts.append("下方可查看智能体每轮输入输出日志。")
    return "".join(parts)


@router.get("/{task_id}/results", response_model=ResultSummary)
def get_results(task_id: str, request: Request) -> ResultSummary:
    deps = request.app.state.deps
    try:
        task = deps.repository.get_task(task_id)
        state = deps.repository.ensure_task_state(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    scheme_row = deps.repository.get_scheme(state.current_scheme_id)
    scheme = SchemeResult(
        scheme_id=scheme_row.scheme_id,
        status=scheme_row.status,
        content_hash=scheme_row.content_hash,
        model_id=scheme_row.model_id,
        provenance=dict((scheme_row.config_json or {}).get("provenance") or {}),
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
    gate = None
    for row in reversed(deps.repository.list_evidence(task_id)):
        if row.action == "A08_GATE":
            gate = {
                "status": row.status,
                "reasons": list(row.observations_json or []),
                "metrics": dict(row.metrics_json or {}),
                **dict(row.gates_json or {}),
            }
            break
    metrics: dict[str, float | None] = {
        key: deps.metrics_by_task.get(task_id, {}).get(key) for key in ("NSE", "KGE", "MAE", "Bias")
    }
    for row in reversed(deps.repository.list_evidence(task_id)):
        if row.action == "A12_EVALUATE_REPORT" and row.metrics_json:
            metrics = {
                k: float(row.metrics_json[k]) if k in row.metrics_json else None
                for k in ("NSE", "KGE", "MAE", "Bias")
            }
            break
    report_artifacts = deps.report_artifacts.get(task_id, ())
    if not report_artifacts:
        for row in reversed(deps.repository.list_evidence(task_id)):
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
        metrics=metrics,
        gate=gate,
        report_artifacts=report_artifacts,
        costs=costs,
        story_zh=_story_zh(
            phase=task.phase,
            scheme=scheme,
            gate=gate,
            metrics=metrics,
            forecasts=forecasts,
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
        # Fallback: reconstruct a thin log from persisted decisions + evidence.
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
                input_world_state=dict(row.get("input_world_state") or {}),
                tool_status=tool_status,
                tool_status_zh=status_zh(tool_status),
                tool_observations=tuple(row.get("tool_observations") or ()),
                tool_metrics={
                    str(k): float(v) for k, v in dict(row.get("tool_metrics") or {}).items()
                },
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
