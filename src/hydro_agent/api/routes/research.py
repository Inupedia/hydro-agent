from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from hydro_agent.evaluation.evidence import HydrologicEvidenceBuilder
from hydro_agent.optimization.ledger import TrialLedgerBuilder

router = APIRouter(prefix="/api/tasks", tags=["research"])


def _workbench_config(repository, task_id: str, current_scheme) -> dict[str, Any]:
    current = dict((current_scheme.config_json or {}).get("workbench") or {})
    if current:
        return current
    for scheme in repository.list_schemes(task_id=task_id):
        workbench = dict((scheme.config_json or {}).get("workbench") or {})
        if workbench:
            return workbench
    return {}


def _protocol(workbench: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "protocol_mode",
        "research_start_date",
        "research_end_date",
        "warmup_start_date",
        "warmup_end_date",
        "calibration_start_date",
        "calibration_end_date",
        "development_start_date",
        "development_end_date",
        "final_test_start_date",
        "final_test_end_date",
        "calibration_history_days",
        "warmup_days",
        "estimated_rolling_forecast_runs",
    )
    return {key: workbench[key] for key in fields if workbench.get(key) is not None}


def _latest_experiment_plan(evidence_rows) -> dict[str, Any] | None:
    row = next((item for item in reversed(evidence_rows) if item.action == "A07_OPTIMIZE"), None)
    if row is None:
        return None
    gates = dict(row.gates_json or {})

    def tokens(value: object) -> list[str]:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(part).strip() for part in value if str(part).strip()]
        return []

    return {
        "plan_id": gates.get("experiment_plan_id"),
        "experiment_signature": gates.get("experiment_signature"),
        "strategy_id": gates.get("strategy_id"),
        "optimizer": gates.get("optimizer"),
        "objective": gates.get("objective_metric") or gates.get("objective"),
        "param_groups": tokens(gates.get("param_groups")),
        "evaluation_budget": gates.get("evaluation_budget"),
        "model_evaluations": gates.get("model_evaluations"),
        "reason_codes": tokens(gates.get("experiment_reason_codes")),
        "evidence_refs": tokens(gates.get("experiment_evidence_refs")),
        "active_parameters": tokens(gates.get("active_parameters")),
        "sensitivity_method": gates.get("sensitivity_method"),
    }


def _load_final_test_evidence(report_root: Path | None, task_id: str) -> dict[str, Any] | None:
    if report_root is None:
        return None
    path = report_root / task_id / "test-hydrograph.json"
    if not path.is_file():
        path = report_root / "test-hydrograph.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    series = payload.get("series") if isinstance(payload, dict) else None
    if not isinstance(series, list):
        return None

    dates: list[date] = []
    observed: list[float | None] = []
    simulated: list[float | None] = []
    for point in series:
        if not isinstance(point, dict) or point.get("window") != "final_test":
            continue
        raw_date = point.get("time")
        if not raw_date:
            continue
        try:
            day = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        dates.append(day)
        observed.append(point.get("observed_m3s"))
        simulated.append(point.get("frozen_m3s"))
    if not dates:
        return None
    try:
        return (
            HydrologicEvidenceBuilder()
            .build(
                window="final_test",
                dates=dates,
                observed=observed,
                simulated=simulated,
            )
            .as_dict()
        )
    except ValueError:
        return None


def _final_test_audit(evidence_rows) -> dict[str, Any]:
    evaluation = next(
        (item for item in reversed(evidence_rows) if item.action == "A12_EVALUATE_REPORT"),
        None,
    )
    observations = list(evaluation.observations_json or []) if evaluation is not None else []
    return {
        "consumed": evaluation is not None,
        "read_only": "final_test_read_only=true" in observations,
        "single_use": any(
            str(item).startswith("final_test_consumption=1/1") for item in observations
        ),
        "window": next(
            (
                str(item).split("=", 1)[1]
                for item in observations
                if str(item).startswith("final_test_window=")
            ),
            None,
        ),
    }


@router.get("/{task_id}/research")
def get_research_summary(task_id: str, request: Request) -> dict[str, Any]:
    deps = request.app.state.deps
    try:
        deps.repository.get_task(task_id)
        state = deps.repository.ensure_task_state(task_id)
        scheme = deps.repository.get_scheme(state.current_scheme_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc

    evidence_rows = deps.repository.list_evidence(task_id)
    ledger = TrialLedgerBuilder().build(evidence_rows)
    workbench = _workbench_config(deps.repository, task_id, scheme)
    report_root = Path(deps.report_root) if deps.report_root else None

    return {
        "task_id": task_id,
        "protocol": _protocol(workbench),
        "latest_experiment_plan": _latest_experiment_plan(evidence_rows),
        "trials": [record.model_dump(mode="json") for record in ledger.records],
        "final_test_evidence": _load_final_test_evidence(report_root, task_id),
        "final_test_audit": _final_test_audit(evidence_rows),
        "contracts": {
            "rolling_continuous_separated": True,
            "final_test_used_for_selection": False,
            "trial_ledger_source": "persisted_evidence",
            "objective_alias": "composite->kge",
        },
    }
