"""Calibration-scientist workbench built on the real deterministic XAJ stack."""

from __future__ import annotations

from hydro_agent.services.calibration_diagnostics import diagnose_prevalidation_window
from hydro_agent.workbench.real import POLICY, RealWorkbenchKernel


def _apply_latest_gate_feedback(result: dict, evidence_rows: list) -> dict:
    """Turn a rejected candidate into a changed, auditable next hypothesis."""

    resolve_index = next(
        (
            index
            for index in range(len(evidence_rows) - 1, -1, -1)
            if evidence_rows[index].action == "A09_RESOLVE"
        ),
        None,
    )
    latest_resolve = evidence_rows[resolve_index] if resolve_index is not None else None
    if latest_resolve is None or latest_resolve.status not in {"KEEP", "ROLLBACK"}:
        return result
    latest_gate = next(
        (
            row
            for row in reversed(evidence_rows[:resolve_index])
            if row.action == "A08_GATE"
        ),
        None,
    )
    if latest_gate is None:
        return result

    gates = dict(latest_gate.gates_json or {})
    reasons = [item for item in str(gates.get("reasons") or "").split(",") if item]
    metrics = dict(latest_gate.metrics_json or {})
    high_flow_failure = any("high_flow_guardrail" in item for item in reasons)
    lead_failure = any("lead_guardrail" in item for item in reasons)
    absolute_failure = any(
        item in {"insufficient_absolute_skill", "insufficient_gbt_scheme_grade"}
        for item in reasons
    )

    if high_flow_failure or lead_failure:
        strategy = "xaj-peak-bias-v1"
        groups = ["runoff", "routing"]
        phenomenon = "Gate 暴露洪峰或分 lead 失真，下一轮聚焦产汇流响应，不重复原实验"
    elif absolute_failure:
        strategy = "xaj-hydro-composite-v1"
        groups = ["evap", "runoff", "routing"]
        phenomenon = "候选虽有局部改善但绝对技巧未过线，下一轮改用全水文过程综合目标"
    else:
        strategy = "xaj-local-refine-v1"
        groups = ["evap", "runoff", "routing"]
        phenomenon = "候选未达到采用条件，吸收 Gate 证据后缩小范围重新检验"

    feedback_hypothesis = {
        "id": "MODEL",
        "strength": 0.95,
        "phenomenon": phenomenon,
        "suggested_action": "A07_OPTIMIZE",
        "suggested_strategy_id": strategy,
        "suggested_param_groups": groups,
        "suggested_objective": "composite",
        "gate_feedback_status": latest_resolve.status,
        "gate_feedback_reasons": reasons,
    }
    result["hypothesis"] = feedback_hypothesis["id"]
    result["phenomenon"] = feedback_hypothesis["phenomenon"]
    result["recommended_action"] = feedback_hypothesis["suggested_action"]
    result["recommended_strategy_id"] = strategy
    result["recommended_param_groups"] = groups
    result["recommended_objective"] = "composite"
    result["hypotheses"] = [feedback_hypothesis, *list(result.get("hypotheses") or [])]
    result["gate_feedback"] = {
        "status": latest_resolve.status,
        "candidate_scheme_id": gates.get("candidate_scheme_id"),
        "reasons": reasons,
        "metrics": metrics,
    }
    return result


class CalibrationScientistWorkbenchKernel(RealWorkbenchKernel):
    """RealWorkbenchKernel with leakage-safe scientific diagnostics.

    The base workbench remains the deterministic executor. This subclass only
    changes *what evidence the Agent is allowed to reason from*: diagnosis is
    built entirely from truth preceding the mutable development window. The
    final-test window is not part of diagnosis or candidate selection.
    """

    def _diagnose(self, task_id: str) -> dict:
        state = self.repository.ensure_task_state(task_id)
        scheme_id = state.current_scheme_id
        if not scheme_id:
            return {
                "hypothesis": "DATA",
                "phenomenon": "尚无当前方案，无法诊断",
                "recommended_action": "A03_VALIDATE_SCHEME",
                "recommended_strategy_id": None,
                "recommended_param_groups": None,
                "recommended_objective": None,
                "hypotheses": [],
                "metrics": {},
                "notes": ["no current scheme"],
            }

        window = self.validation_gate.window_for(task_id)
        result = diagnose_prevalidation_window(
            repository=self.repository,
            forecast_service=self.forecast,
            source=self.source,
            policy=POLICY,
            task_id=task_id,
            scheme_id=scheme_id,
            validation_start=window.start,
            nse_good_enough=self.skills.nse_good_enough(),
        )
        result = _apply_latest_gate_feedback(
            result, self.repository.list_evidence(task_id)
        )
        notes = list(result.get("notes") or [])
        notes.insert(0, f"scheme_id={scheme_id}")
        notes.insert(
            1,
            f"held_out_development_window={window.start.isoformat()}..{window.end.isoformat()}",
        )
        feedback = result.get("gate_feedback")
        if isinstance(feedback, dict):
            notes.insert(
                2,
                "gate_feedback="
                + str(feedback.get("status") or "unknown")
                + ":"
                + ",".join(str(item) for item in feedback.get("reasons") or []),
            )
        result["notes"] = notes
        return result
