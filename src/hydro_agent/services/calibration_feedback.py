"""Compose independent Gate evidence back into the next calibration diagnosis."""

from __future__ import annotations


def apply_latest_gate_feedback(result: dict, evidence_rows: list) -> dict:
    """Refine the next experiment hypothesis from the latest resolved Gate.

    This is shared evidence composition, not provider policy. Product API, smoke,
    deterministic providers and LLM providers must all see the same diagnosis.
    """

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
        (row for row in reversed(evidence_rows[:resolve_index]) if row.action == "A08_GATE"),
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
        item in {"insufficient_absolute_skill", "insufficient_gbt_scheme_grade"} for item in reasons
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
