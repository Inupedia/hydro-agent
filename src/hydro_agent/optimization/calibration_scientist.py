"""Structured calibration-scientist contracts and deterministic Skill handlers.

Skill / Agent reasoning may propose what to test; these typed contracts are the
only bridge into deterministic experiment planning. Continuous XAJ parameter
vectors are intentionally absent from ``CalibrationPlan``.

Callers that need audited Skill activation should go through
``hydro_agent.skills.orchestration.SkillOrchestrator`` rather than calling the
handlers below directly.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.optimization.contracts import DirectionalProbeResult
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry
from hydro_agent.skills.expert import ExpertPriorEngine
from hydro_agent.skills.governance import KnowledgeQueryContext

ParameterGroup = str
ProcessLayer = Literal[
    "snow",
    "evap",
    "soil",
    "runoff",
    "groundwater",
    "routing",
    "production",
    "exchange",
    "surface",
    "intermediate",
    "base",
    "upper",
    "lower",
    "percolation",
    "mixed",
    "unknown",
]
ObjectiveName = Literal["nse", "peak", "composite"]
OptimizerName = Literal["dds", "sce-ua", "random-search", "manual"]
SearchScope = Literal["global", "local"]
SearchAdjustment = Literal["keep", "broaden_within_absolute_bounds", "hold_absolute_bounds"]
HypothesisStatus = Literal["supported", "refuted", "inconclusive", "adopted_unqualified"]
AdjustmentDirection = Literal[
    "increase_water_loss",
    "decrease_water_loss",
    "increase_runoff_response",
    "decrease_runoff_response",
    "accelerate_routing",
    "delay_routing",
    "increase_fast_component",
    "increase_slow_component",
    "unknown",
]


class EvidenceInterpretation(FrozenModel):
    """Model-agnostic reading of HydrologicEvidence / diagnosis metrics."""

    dominant_patterns: tuple[str, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()
    contradictory_evidence_ids: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    metrics_summary: tuple[str, ...] = ()


class DiagnosisHypothesis(FrozenModel):
    """Falsifiable hydrologic hypothesis before optimizer search begins."""

    hypothesis_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    phenomenon: str = Field(min_length=1)
    process_layer: ProcessLayer = "unknown"
    parameter_groups: tuple[ParameterGroup, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()
    contradictory_evidence_ids: tuple[str, ...] = ()
    falsification_conditions: tuple[str, ...] = ()
    diagnostic_signature: tuple[str, ...] = ()
    direction: AdjustmentDirection = "unknown"
    direction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    direction_evidence_ids: tuple[str, ...] = ()
    verification_required: bool = True
    recommended_strategy_id: str | None = None
    recommended_objective: ObjectiveName | None = None

    def as_calibration_hypothesis(self) -> CalibrationHypothesis:
        return CalibrationHypothesis(
            hypothesis=self.hypothesis_id,
            confidence=self.confidence,
            phenomenon=self.phenomenon,
            evidence=tuple(
                dict.fromkeys(
                    (
                        *self.supporting_evidence_ids,
                        *self.contradictory_evidence_ids,
                    )
                )
            ),
        )


class CalibrationHypothesis(FrozenModel):
    """Compact hypothesis payload embedded in ``CalibrationPlan`` (stable API)."""

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
    evaluation_budget: int = Field(ge=2, le=10_000)
    search_adjustment: SearchAdjustment = "keep"
    knowledge_refs: tuple[str, ...] = ()
    expert_notes: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)
    # Source-addressable upstream contracts for audit / Skill invocation ledger.
    evidence_interpretation: EvidenceInterpretation | None = None
    diagnosis_hypothesis: DiagnosisHypothesis | None = None
    direction_verification_status: Literal[
        "not_required", "supported", "refuted", "inconclusive"
    ] = "not_required"
    direction_evidence_ids: tuple[str, ...] = ()
    next_step: Literal["optimize", "re-diagnose"] = "optimize"

    @property
    def tunes_raw_parameter_vector(self) -> bool:
        return False


class CalibrationReflection(FrozenModel):
    gate_status: Literal["ACCEPT", "KEEP", "ROLLBACK"]
    qualification_status: Literal["QUALIFIED", "UNQUALIFIED", "NOT_EVALUATED"] = "NOT_EVALUATED"
    conclusion: str = Field(min_length=1)
    next_step: Literal["freeze", "re-diagnose", "rollback", "handover"]
    evidence: tuple[str, ...] = ()


class ExperimentReview(FrozenModel):
    """Result-review contract after Gate / Resolve (Skill-shaped, code-validated)."""

    hypothesis_status: HypothesisStatus
    gate_status: Literal["ACCEPT", "KEEP", "ROLLBACK"]
    qualification_status: Literal["QUALIFIED", "UNQUALIFIED", "NOT_EVALUATED"] = "NOT_EVALUATED"
    supporting_evidence_ids: tuple[str, ...] = ()
    contradictory_evidence_ids: tuple[str, ...] = ()
    lessons: tuple[str, ...] = ()
    recommended_next_experiment: Literal["freeze", "re-diagnose", "rollback", "handover"]
    conclusion: str = Field(min_length=1)

    def as_reflection(self) -> CalibrationReflection:
        return CalibrationReflection(
            gate_status=self.gate_status,
            qualification_status=self.qualification_status,
            conclusion=self.conclusion,
            next_step=self.recommended_next_experiment,
            evidence=(
                *self.supporting_evidence_ids,
                *self.contradictory_evidence_ids,
                *self.lessons,
            ),
        )


def _normalize_groups(
    raw_groups: object,
    fallback: tuple[str, ...],
    *,
    model_id: str | None = None,
) -> tuple[str, ...]:
    if isinstance(raw_groups, str):
        groups = tuple(item.strip() for item in raw_groups.split(",") if item.strip())
    elif isinstance(raw_groups, (list, tuple)):
        groups = tuple(str(item).strip() for item in raw_groups if str(item).strip())
    else:
        groups = ()
    from hydro_agent.models.diagnosis_defaults import allowed_param_groups

    allowed = allowed_param_groups(model_id)
    if not groups or any(item not in allowed for item in groups):
        return tuple(fallback)
    return groups


def _name_list(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        return tuple(item.strip() for item in raw.split(",") if item.strip())
    if isinstance(raw, (list, tuple)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def _process_layer(groups: tuple[str, ...]) -> ProcessLayer:
    unique = tuple(dict.fromkeys(groups))
    known = {
        "snow",
        "evap",
        "soil",
        "runoff",
        "groundwater",
        "routing",
        "production",
        "exchange",
        "surface",
        "intermediate",
        "base",
        "upper",
        "lower",
        "percolation",
    }
    if len(unique) == 1 and unique[0] in known:
        return unique[0]  # type: ignore[return-value]
    if len(unique) > 1:
        return "mixed"
    return "unknown"


def _default_strategy_id(diagnosis: dict[str, Any] | None = None) -> str:
    model_id = "xaj"
    if isinstance(diagnosis, dict):
        raw = diagnosis.get("model_id")
        if raw:
            model_id = str(raw)
    try:
        from hydro_agent.models.registry import default_model_registry

        return default_model_registry().default_strategy_id(model_id)
    except KeyError:
        return f"{model_id}-bounded-v1"


def _search_adjustment(diagnosis: dict[str, Any]) -> SearchAdjustment:
    if _name_list(diagnosis.get("absolute_boundary_hits")):
        return "hold_absolute_bounds"
    if _name_list(diagnosis.get("local_boundary_hits")):
        return "broaden_within_absolute_bounds"
    return "keep"


def _progressive_strategy(
    *,
    recommended_strategy_id: str,
    previous_strategy_id: str | None,
    adjustment: str | None,
    registry: CalibrationStrategyRegistry,
) -> str:
    if adjustment != "broaden_within_absolute_bounds":
        return recommended_strategy_id
    source_strategy_id = previous_strategy_id or recommended_strategy_id
    from hydro_agent.models.diagnosis_defaults import model_id_from_strategy_id

    model_prefix = model_id_from_strategy_id(source_strategy_id) or "xaj"
    broadened = f"{model_prefix}-broadened-refine-v1"
    bounded = f"{model_prefix}-bounded-v1"
    if source_strategy_id == broadened:
        return bounded if bounded in {s for s in registry.list_ids()} else recommended_strategy_id
    current = registry.get(source_strategy_id)
    if current.local_scale is None:
        return recommended_strategy_id
    try:
        registry.get(broadened)
        return broadened
    except KeyError:
        return recommended_strategy_id


def _locked_objective(
    diagnosis: dict[str, Any], campaign_objective: ObjectiveName | None
) -> ObjectiveName | None:
    raw = campaign_objective
    if raw is None and diagnosis.get("campaign_objective") is not None:
        raw = str(diagnosis["campaign_objective"])  # type: ignore[assignment]
    if raw is None:
        return None
    if raw not in {"nse", "peak", "composite"}:
        raise ValueError(f"unsupported campaign objective: {raw}")
    return raw  # type: ignore[return-value]


def interpret_evidence(diagnosis: dict[str, Any] | Any) -> EvidenceInterpretation:
    """Turn diagnosis metrics/notes into a model-agnostic evidence reading."""

    from hydro_agent.agent.hydrologic_evidence import HydrologicEvidence

    evidence = (
        diagnosis
        if isinstance(diagnosis, HydrologicEvidence)
        else HydrologicEvidence.from_diagnosis(diagnosis)
    )
    metrics_summary = list(evidence.metric_lines())
    notes = evidence.notes[:8]
    phenomenon = evidence.phenomenon.strip()
    patterns = tuple(item for item in (phenomenon, *notes[:3], *metrics_summary[:4]) if item)
    uncertainties: list[str] = []
    if not metrics_summary:
        uncertainties.append("缺少可引用的数值指标摘要")
    if not phenomenon:
        uncertainties.append("尚未形成明确误差现象描述")

    required: list[str] = []
    joined = " ".join(patterns).lower()
    joined_zh = "".join(patterns)
    if "peak" in joined or "洪峰" in joined_zh:
        required.append("flood_peak_and_timing")
    if any(token in joined_zh or token in joined for token in ("水量", "PBIAS", "pbias", "volume")):
        required.append("water_balance")
    if evidence.flood_events:
        required.append("flood_peak_and_timing")
    if evidence.overall.pbias_percent is not None:
        required.append("water_balance")

    supporting = tuple(dict.fromkeys((*metrics_summary, *notes[:4])))
    return EvidenceInterpretation(
        dominant_patterns=patterns[:6] or ("未形成明确误差模式",),
        supporting_evidence_ids=supporting,
        contradictory_evidence_ids=evidence.contradictory_evidence_ids,
        uncertainties=tuple(uncertainties),
        required_evidence=tuple(dict.fromkeys(required)),
        metrics_summary=tuple(metrics_summary),
    )


def _packet_direction(
    evidence: Any,
    *,
    groups: tuple[str, ...],
    confidence: float,
) -> tuple[
    tuple[str, ...],
    AdjustmentDirection,
    float,
    tuple[str, ...],
    tuple[str, ...],
]:
    """Infer process-level adjustment direction from deterministic P0 evidence.

    This function never proposes raw parameter values. It only recognizes
    repeated process signatures that must be verified by deterministic probes
    before numerical search can use them.
    """

    events = tuple(
        event
        for event in getattr(evidence, "flood_events", ())
        if getattr(event, "status", None) in {None, "available"}
    )
    signature: list[str] = []
    supporting: list[str] = []
    contradictory: list[str] = []
    direction: AdjustmentDirection = "unknown"
    agreement = 0.0

    comparable = [
        event
        for event in events
        if event.timing_lag_steps is not None and event.volume_relative_error is not None
    ]
    neutral = [
        event for event in comparable if abs(float(event.volume_relative_error)) <= 0.05
    ]
    late = [event for event in neutral if float(event.timing_lag_steps) >= 1.0]
    early = [event for event in neutral if float(event.timing_lag_steps) <= -1.0]

    if "routing" in groups and len(late) >= 2:
        direction = "accelerate_routing"
        supporting = [event.event_id for event in late if event.event_id]
        contradictory = [event.event_id for event in early if event.event_id]
        agreement = len(late) / max(1, len(neutral))
        signature.extend(("water_balance_near_neutral", "repeated_late_peaks"))
    elif "routing" in groups and len(early) >= 2:
        direction = "delay_routing"
        supporting = [event.event_id for event in early if event.event_id]
        contradictory = [event.event_id for event in late if event.event_id]
        agreement = len(early) / max(1, len(neutral))
        signature.extend(("water_balance_near_neutral", "repeated_early_peaks"))

    pbias = getattr(getattr(evidence, "water_balance", None), "pbias_percent", None)
    if pbias is None:
        pbias = getattr(getattr(evidence, "overall", None), "pbias_percent", None)
    timing_values = [
        abs(float(event.timing_lag_steps))
        for event in events
        if event.timing_lag_steps is not None
    ]
    timing_acceptable = bool(timing_values) and max(timing_values) < 1.0

    if direction == "unknown" and pbias is not None and abs(float(pbias)) >= 10.0:
        if timing_acceptable or not timing_values:
            if any(group in groups for group in ("evap", "runoff", "production")):
                direction = (
                    "increase_water_loss" if float(pbias) > 0.0 else "decrease_water_loss"
                )
                signature.append("water_balance_bias_dominant")
                supporting = [
                    event.event_id
                    for event in events
                    if event.event_id and event.volume_relative_error is not None
                ]
                agreement = 1.0

    direction_confidence = (
        max(0.0, min(1.0, confidence * agreement))
        if direction != "unknown"
        else 0.0
    )
    return (
        tuple(dict.fromkeys(signature)),
        direction,
        direction_confidence,
        tuple(dict.fromkeys(supporting)),
        tuple(dict.fromkeys(contradictory)),
    )


def form_diagnosis_hypothesis(
    interpretation: EvidenceInterpretation,
    diagnosis: dict[str, Any] | Any,
    *,
    parameter_groups: tuple[str, ...] = (),
    recommended_strategy_id: str | None = None,
    recommended_objective: ObjectiveName | None = None,
) -> DiagnosisHypothesis:
    """Build a falsifiable hypothesis from evidence interpretation + diagnosis fields."""

    from hydro_agent.agent.hydrologic_evidence import HydrologicEvidence

    evidence = (
        diagnosis
        if isinstance(diagnosis, HydrologicEvidence)
        else HydrologicEvidence.from_diagnosis(diagnosis)
    )
    payload = evidence.as_diagnosis_dict()
    hypotheses = list(payload.get("hypotheses") or [])
    primary_id = str(payload.get("hypothesis") or "UNKNOWN")
    confidence = 0.5
    for item in hypotheses:
        if str(item.get("id")) == primary_id:
            try:
                confidence = float(item.get("strength"))
            except (TypeError, ValueError):
                confidence = 0.5
            break
    confidence = max(0.0, min(1.0, confidence))
    model_id = str(payload.get("model_id") or "xaj")
    groups = _normalize_groups(
        parameter_groups or payload.get("recommended_param_groups"), (), model_id=model_id
    )
    layer = _process_layer(groups)
    phenomenon = str(payload.get("phenomenon") or interpretation.dominant_patterns[0])

    falsification: list[str] = []
    if "routing" in groups:
        falsification.append("若洪量显著偏高而峰值/退水正常，则 routing 假设不足")
    if "runoff" in groups or "evap" in groups:
        falsification.append("若峰值偏差主导而水量接近无偏，则水量/产流假设不足")
    if not falsification:
        falsification.append("若下一轮证据与当前现象矛盾，则应更换假设而非重复同组搜索")
    falsification.extend(interpretation.uncertainties[:2])

    objective = recommended_objective
    if objective is None:
        raw_obj = payload.get("recommended_objective")
        if raw_obj in {"nse", "peak", "composite"}:
            objective = raw_obj  # type: ignore[assignment]

    strategy_id = recommended_strategy_id or (
        str(payload.get("recommended_strategy_id"))
        if payload.get("recommended_strategy_id")
        else None
    )

    (
        diagnostic_signature,
        direction,
        direction_confidence,
        direction_evidence_ids,
        direction_contradictions,
    ) = _packet_direction(evidence, groups=groups, confidence=confidence)
    contradictory_ids = tuple(
        dict.fromkeys(
            (
                *interpretation.contradictory_evidence_ids,
                *direction_contradictions,
            )
        )
    )
    if direction == "accelerate_routing":
        falsification.append(
            "若 routing 局部扰动不能缩短峰现滞后且保持洪量，则 accelerate_routing 假设不成立"
        )
    elif direction == "delay_routing":
        falsification.append(
            "若 routing 局部扰动不能减小提前峰现且保持洪量，则 delay_routing 假设不成立"
        )
    elif direction in {"increase_water_loss", "decrease_water_loss"}:
        falsification.append(
            "若水量相关参数局部扰动不能减小系统水量偏差，则当前水量方向假设不成立"
        )

    return DiagnosisHypothesis(
        hypothesis_id=primary_id,
        confidence=confidence,
        phenomenon=phenomenon,
        process_layer=layer,
        parameter_groups=groups,  # type: ignore[arg-type]
        supporting_evidence_ids=interpretation.supporting_evidence_ids,
        contradictory_evidence_ids=contradictory_ids,
        falsification_conditions=tuple(dict.fromkeys(falsification)),
        diagnostic_signature=diagnostic_signature,
        direction=direction,
        direction_confidence=direction_confidence,
        direction_evidence_ids=direction_evidence_ids,
        verification_required=True,
        recommended_strategy_id=strategy_id,
        recommended_objective=objective,
    )


def plan_from_hypothesis(
    hypothesis: DiagnosisHypothesis,
    diagnosis: dict[str, Any],
    *,
    interpretation: EvidenceInterpretation | None = None,
    strategies: CalibrationStrategyRegistry | None = None,
    expert_priors: ExpertPriorEngine | None = None,
    campaign_objective: ObjectiveName | None = None,
    knowledge_context: KnowledgeQueryContext | None = None,
    direction_verification: DirectionalProbeResult | None = None,
) -> CalibrationPlan:
    """Compile a legal ``CalibrationPlan`` from a typed diagnosis hypothesis."""

    registry = strategies or CalibrationStrategyRegistry()
    model_id = str(diagnosis.get("model_id") or "xaj")
    fallback = _default_strategy_id(diagnosis)
    recommended_strategy_id = hypothesis.recommended_strategy_id or fallback
    try:
        strategy = registry.get(recommended_strategy_id, model_id=model_id)
    except KeyError:
        recommended_strategy_id = fallback
        strategy = registry.get(recommended_strategy_id, model_id=model_id)

    groups = hypothesis.parameter_groups or tuple(strategy.param_groups)
    groups = _normalize_groups(groups, tuple(strategy.param_groups), model_id=model_id)
    objective = str(hypothesis.recommended_objective or strategy.objective)
    if objective not in {"nse", "peak", "composite"}:
        objective = strategy.objective
    locked_objective = _locked_objective(diagnosis, campaign_objective)

    basin_attributes = diagnosis.get("basin_attributes")
    prior_engine = expert_priors or ExpertPriorEngine()
    advice = prior_engine.advise(
        diagnosis,
        basin_attributes=basin_attributes if isinstance(basin_attributes, dict) else None,
        governance_context=knowledge_context,
    )
    if advice.recommended_param_groups:
        groups = _normalize_groups(advice.recommended_param_groups, groups, model_id=model_id)
    if locked_objective is None and advice.recommended_objective in {"nse", "peak", "composite"}:
        objective = advice.recommended_objective
    if locked_objective is not None:
        objective = locked_objective

    adjustment = _search_adjustment(diagnosis)
    previous_raw = diagnosis.get("previous_strategy_id")
    previous_strategy_id = str(previous_raw) if previous_raw else None
    try:
        strategy_id = _progressive_strategy(
            recommended_strategy_id=recommended_strategy_id,
            previous_strategy_id=previous_strategy_id,
            adjustment=adjustment,
            registry=registry,
        )
        strategy = registry.get(strategy_id, model_id=model_id)
    except KeyError:
        strategy_id = recommended_strategy_id
        strategy = registry.get(strategy_id, model_id=model_id)

    scope: SearchScope = "local" if strategy.local_scale is not None else "global"
    prior_text = ""
    if advice.matched_prior_refs:
        prior_text = (
            f" 专家先验[{advice.status}/{advice.authority}]="
            f"{','.join(advice.matched_prior_refs)}；"
        )
    search_text = ""
    if adjustment == "broaden_within_absolute_bounds":
        search_text = " 局部搜索触边界，按协议逐级放宽但不越过产品绝对参数边界；"
    elif adjustment == "hold_absolute_bounds":
        search_text = " 已触及绝对参数边界，本轮禁止继续外扩并保留为诊断证据；"
    objective_text = ""
    expert_notes = list(advice.notes)
    if locked_objective is not None:
        objective_text = f" campaign 主目标锁定为 {locked_objective}；"
        if advice.recommended_objective and advice.recommended_objective != locked_objective:
            expert_notes.append(
                f"专家目标建议 {advice.recommended_objective} 未采用：campaign objective 已锁定为 "
                f"{locked_objective}。"
            )

    refined = hypothesis.model_copy(
        update={
            "parameter_groups": groups,
            "recommended_strategy_id": strategy_id,
            "recommended_objective": objective,  # type: ignore[dict-item]
            "process_layer": _process_layer(groups),
        }
    )
    reading = interpretation or interpret_evidence(diagnosis)
    verification_status: Literal[
        "not_required", "supported", "refuted", "inconclusive"
    ] = "not_required"
    direction_evidence_ids: tuple[str, ...] = ()
    next_step: Literal["optimize", "re-diagnose"] = "optimize"
    if direction_verification is not None:
        if direction_verification.requested_direction != refined.direction:
            raise ValueError("direction verification does not match hypothesis direction")
        verification_status = direction_verification.status
        direction_evidence_ids = tuple(direction_verification.evidence_ids)
        if direction_verification.status in {"refuted", "inconclusive"}:
            next_step = "re-diagnose"

    return CalibrationPlan(
        hypothesis=refined.as_calibration_hypothesis(),
        strategy_id=strategy_id,
        parameter_groups=groups,  # type: ignore[arg-type]
        objective=objective,  # type: ignore[arg-type]
        optimizer=strategy.optimizer,
        search_scope=scope,
        local_scale=strategy.local_scale,
        evaluation_budget=strategy.evaluation_budget,
        search_adjustment=adjustment,
        knowledge_refs=advice.matched_prior_refs,
        expert_notes=tuple(expert_notes),
        rationale=(
            f"基于 {refined.hypothesis_id} 假设（{refined.process_layer}），"
            f"仅开放 {','.join(groups)} 参数组；"
            f"由 {strategy.optimizer} 在确定性边界内完成至多 {strategy.evaluation_budget} 次模型评估，"
            "Agent 不直接给参数值。"
            f"{objective_text}{prior_text}{search_text}"
        ),
        evidence_interpretation=reading,
        diagnosis_hypothesis=refined,
        direction_verification_status=verification_status,
        direction_evidence_ids=direction_evidence_ids,
        next_step=next_step,
    )


def plan_from_diagnosis(
    diagnosis: dict[str, Any],
    *,
    strategies: CalibrationStrategyRegistry | None = None,
    expert_priors: ExpertPriorEngine | None = None,
    campaign_objective: ObjectiveName | None = None,
    knowledge_context: KnowledgeQueryContext | None = None,
) -> CalibrationPlan:
    """Orchestrate Evidence → Hypothesis → Plan via Skill invocations."""

    from hydro_agent.skills.orchestration import SkillOrchestrator

    plan, _invocations = SkillOrchestrator(
        strategies=strategies,
        expert_priors=expert_priors,
    ).plan_calibration(
        diagnosis,
        campaign_objective=campaign_objective,
        knowledge_context=knowledge_context,
    )
    return plan


def review_experiment(
    plan: CalibrationPlan,
    *,
    gate_status: str,
    qualification_status: str = "NOT_EVALUATED",
    reasons: tuple[str, ...] = (),
) -> ExperimentReview:
    status = gate_status if gate_status in {"ACCEPT", "KEEP", "ROLLBACK"} else "KEEP"
    qualification = (
        qualification_status
        if qualification_status in {"QUALIFIED", "UNQUALIFIED", "NOT_EVALUATED"}
        else "NOT_EVALUATED"
    )
    supporting = (
        f"strategy={plan.strategy_id}",
        f"optimizer={plan.optimizer}",
        f"hypothesis={plan.hypothesis.hypothesis}",
        f"search_adjustment={plan.search_adjustment}",
        f"qualification={qualification}",
        *tuple(f"knowledge={item}" for item in plan.knowledge_refs),
    )
    lessons = tuple(reasons)
    if status == "ACCEPT" and qualification == "QUALIFIED":
        return ExperimentReview(
            hypothesis_status="supported",
            gate_status="ACCEPT",
            qualification_status="QUALIFIED",
            supporting_evidence_ids=supporting,
            contradictory_evidence_ids=(),
            lessons=lessons,
            recommended_next_experiment="freeze",
            conclusion="候选既优于当前方案，也通过独立资格评价。",
        )
    if status == "ACCEPT":
        return ExperimentReview(
            hypothesis_status="adopted_unqualified",
            gate_status="ACCEPT",
            qualification_status=qualification,  # type: ignore[arg-type]
            supporting_evidence_ids=supporting,
            contradictory_evidence_ids=(),
            lessons=lessons,
            recommended_next_experiment="re-diagnose",
            conclusion="候选值得采用为新的工作基线，但尚未达到最终资格条件。",
        )
    if status == "ROLLBACK":
        return ExperimentReview(
            hypothesis_status="refuted",
            gate_status="ROLLBACK",
            qualification_status=qualification,  # type: ignore[arg-type]
            supporting_evidence_ids=(),
            contradictory_evidence_ids=supporting,
            lessons=lessons,
            recommended_next_experiment="rollback",
            conclusion="候选在独立验证中退化，本轮率定假设不能继续沿用。",
        )
    return ExperimentReview(
        hypothesis_status="inconclusive",
        gate_status="KEEP",
        qualification_status=qualification,  # type: ignore[arg-type]
        supporting_evidence_ids=(),
        contradictory_evidence_ids=supporting,
        lessons=lessons,
        recommended_next_experiment="re-diagnose",
        conclusion="证据不足以采用候选；保留当前方案并重新诊断，而不是继续盲目搜索。",
    )


def reflect_on_gate(
    plan: CalibrationPlan,
    *,
    gate_status: str,
    qualification_status: str = "NOT_EVALUATED",
    reasons: tuple[str, ...] = (),
) -> CalibrationReflection:
    return review_experiment(
        plan,
        gate_status=gate_status,
        qualification_status=qualification_status,
        reasons=reasons,
    ).as_reflection()
