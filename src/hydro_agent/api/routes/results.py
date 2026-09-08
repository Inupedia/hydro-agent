from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from hydro_agent.api.schemas import ForecastResult, ResultSummary, SchemeResult

router = APIRouter(prefix="/api/tasks", tags=["results"])


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
    return ResultSummary(
        task_id=task_id,
        phase=task.phase,  # type: ignore[arg-type]
        scheme=scheme,
        forecasts=forecasts,
        metrics=metrics,
        gate=gate,
        report_artifacts=report_artifacts,
        costs=costs,
    )


@router.get("/{task_id}/forecasts", response_model=list[ForecastResult])
def get_forecasts(task_id: str, request: Request) -> list[ForecastResult]:
    return list(get_results(task_id, request).forecasts)


@router.get("/{task_id}/report/{artifact_name}")
def get_report_artifact(task_id: str, artifact_name: str, request: Request):
    deps = request.app.state.deps
    if artifact_name not in {"report.json", "report.md"}:
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
