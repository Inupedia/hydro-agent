"""Structured calibration-scientist contracts.

The Agent owns the scientific decision (what to test and why); the numerical
optimizer owns the continuous parameter search. No raw XAJ parameter vector is
part of ``CalibrationPlan`` by design.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.knowledge.expert import ExpertKnowledgeRepository
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry

ParameterGroup = Literal["evap", "runoff", "routing"]
ObjectiveName = Literal["nse", "peak", "composite"]
OptimizerName = Literal["sce-ua", "random-search", "manual"]
SearchScope = Literal["global", "local"]


class CalibrationHypothesis(FrozenModel):
    hypothesis: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    phenomenon: str = Field(min_length=1)
    evidence: tuple[str, ...] = ()


class CalibrationPlan(FrozenModel):
    hypothesis: CalibrationHypothesis
    strategy_id: str = Field(min_length=1)
    parameter_groups: tuple[ParameterGroup, ...]
    objective: ObjectiveName
    optimizer: OptimizerName
    search_scope: SearchScope
    local_scale: float | None = Field(default=None, ge=0.0, le=1.0)
    evaluation_budget: int = Field(ge=2, le=500)
    knowledge_refs: tuple[str, ...] = ()
    expert_notes: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)

    @property
    def tunes_raw_parameter_vector(self) -> bool:
        """Audit/UI guard: plans select groups, never raw parameter vectors."""
        return False


class CalibrationReflection(FrozenModel):
    gate_status: Literal["ACCEPT", "KEEP", "ROLLBACK"]
    conclusion: str = Field(min_length=1)
    next_step: Literal["freeze", "re-diagnose", "rollback", "handover"]
    evidence: tuple[str, ...] = ()


def _normalize_groups(raw_groups: object, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(raw_groups, str):
        groups = tuple(item.strip() for item in raw_groups.split(",") if item.strip())
    elif isinstance(raw_groups, (list, tuple)):
        groups = tuple(str(item).strip() for item in raw_groups if str(item).strip())
    else:
        groups = ()
    allowed = {"evap", "runoff", "routing"}
    if not groups or any(item not in allowed for item in groups):
        return tuple(fallback)
    return groups


def plan_from_diagnosis(
    diagnosis: dict[str, Any],
    *,
    strategies: CalibrationStrategyRegistry | None = None,
    expert_knowledge: ExpertKnowledgeRepository | None = None,
) -> CalibrationPlan:
    """Translate a diagnosis into an auditable optimization experiment.

    Evidence is primary. Expert priors may refine the parameter group/objective
    choice, but remain advisory metadata and never alter validation Gate rules.
    """

    registry = strategies or CalibrationStrategyRegistry()
    strategy_id = str(diagnosis.get("recommended_strategy_id") or "xaj-bounded-v1")
    try:
        strategy = registry.get(strategy_id)
    except KeyError:
        strategy_id = "xaj-bounded-v1"
        strategy = registry.get(strategy_id)

    groups = _normalize_groups(
        diagnosis.get("recommended_param_groups"), tuple(strategy.param_groups)
    )

    objective = str(diagnosis.get("recommended_objective") or strategy.objective)
    if objective not in {"nse", "peak", "composite"}:
        objective = strategy.objective

    basin_attributes = diagnosis.get("basin_attributes")
    expert = expert_knowledge or ExpertKnowledgeRepository()
    advice = expert.advise(
        diagnosis,
        basin_attributes=basin_attributes if isinstance(basin_attributes, dict) else None,
    )
    if advice.recommended_param_groups:
        groups = _normalize_groups(advice.recommended_param_groups, groups)
    if advice.recommended_objective in {"nse", "peak", "composite"}:
        objective = advice.recommended_objective

    hypotheses = list(diagnosis.get("hypotheses") or [])
    primary_id = str(diagnosis.get("hypothesis") or "UNKNOWN")
    confidence = 0.5
    for item in hypotheses:
        if str(item.get("id")) == primary_id:
            try:
                confidence = float(item.get("strength"))
            except (TypeError, ValueError):
                confidence = 0.5
            break
    confidence = max(0.0, min(1.0, confidence))
    phenomenon = str(diagnosis.get("phenomenon") or "未形成明确误差模式")

    evidence: list[str] = []
    for key, value in dict(diagnosis.get("metrics") or {}).items():
        if isinstance(value, (int, float)):
            evidence.append(f"{key}={float(value):.6g}")
    evidence.extend(str(note) for note in (diagnosis.get("notes") or ())[:4])

    scope: SearchScope = "local" if strategy.local_scale is not None else "global"
    prior_text = ""
    if advice.matched_rule_ids:
        prior_text = (
            f" 专家先验[{advice.status}/{advice.authority}]="
            f"{','.join(advice.matched_rule_ids)}；"
        )
    return CalibrationPlan(
        hypothesis=CalibrationHypothesis(
            hypothesis=primary_id,
            confidence=confidence,
            phenomenon=phenomenon,
            evidence=tuple(evidence),
        ),
        strategy_id=strategy_id,
        parameter_groups=groups,  # type: ignore[arg-type]
        objective=objective,  # type: ignore[arg-type]
        optimizer=strategy.optimizer,
        search_scope=scope,
        local_scale=strategy.local_scale,
        evaluation_budget=strategy.evaluation_budget,
        knowledge_refs=advice.matched_rule_ids,
        expert_notes=advice.notes,
        rationale=(
            f"基于 {primary_id} 假设，仅开放 {','.join(groups)} 参数组；"
            f"由 {strategy.optimizer} 在确定性边界内完成数值搜索，Agent 不直接给参数值。"
            f"{prior_text}"
        ),
    )


def reflect_on_gate(
    plan: CalibrationPlan,
    *,
    gate_status: str,
    reasons: tuple[str, ...] = (),
) -> CalibrationReflection:
    """Turn independent validation into the next scientific decision."""

    status = gate_status if gate_status in {"ACCEPT", "KEEP", "ROLLBACK"} else "KEEP"
    evidence = (
        f"strategy={plan.strategy_id}",
        f"optimizer={plan.optimizer}",
        f"hypothesis={plan.hypothesis.hypothesis}",
        *tuple(f"knowledge={item}" for item in plan.knowledge_refs),
        *tuple(reasons),
    )
    if status == "ACCEPT":
        return CalibrationReflection(
            gate_status="ACCEPT",
            conclusion="独立验证支持本轮假设与候选方案。",
            next_step="freeze",
            evidence=evidence,
        )
    if status == "ROLLBACK":
        return CalibrationReflection(
            gate_status="ROLLBACK",
            conclusion="候选在独立验证中退化，本轮率定假设不能继续沿用。",
            next_step="rollback",
            evidence=evidence,
        )
    return CalibrationReflection(
        gate_status="KEEP",
        conclusion="证据不足以接受候选；保留基线并重新诊断，而不是继续盲目搜索。",
        next_step="re-diagnose",
        evidence=evidence,
    )
