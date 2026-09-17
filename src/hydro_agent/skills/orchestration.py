"""Skill invocation: activate one package → typed contract → audit record.

Decision providers orchestrate through this module. Continuous XAJ search, Gate,
and metrics stay outside Skills. Deterministic handlers live in
``optimization.calibration_scientist`` and are invoked here by Skill id.
"""

from __future__ import annotations

from typing import Any, Literal

from hydro_agent.agent.hydrologic_evidence import HydrologicEvidence
from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.optimization.calibration_scientist import (
    CalibrationPlan,
    DiagnosisHypothesis,
    EvidenceInterpretation,
    ExperimentReview,
    form_diagnosis_hypothesis,
    interpret_evidence,
    plan_from_hypothesis,
    review_experiment,
)
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry
from hydro_agent.skills import (
    EVIDENCE_REVIEW_SKILL_ID,
    EXPERIMENT_DESIGN_SKILL_ID,
    RESULT_REVIEW_SKILL_ID,
    SkillRegistry,
)
from hydro_agent.skills.expert import ExpertPriorEngine
from hydro_agent.skills.governance import KnowledgeQueryContext
from hydro_agent.skills.reference_policy import references_for_view

OutputContractName = Literal[
    "EvidenceInterpretation",
    "DiagnosisHypothesis",
    "CalibrationPlan",
    "ExperimentReview",
]

_BASE_SKILL_OUTPUT_CONTRACT: dict[str, OutputContractName] = {
    EVIDENCE_REVIEW_SKILL_ID: "EvidenceInterpretation",
    EXPERIMENT_DESIGN_SKILL_ID: "CalibrationPlan",
    RESULT_REVIEW_SKILL_ID: "ExperimentReview",
}


def skill_output_contract() -> dict[str, OutputContractName]:
    """Core contracts plus every registered plugin diagnosis skill."""

    contracts = dict(_BASE_SKILL_OUTPUT_CONTRACT)
    try:
        from hydro_agent.models.registry import default_model_registry

        for descriptor in default_model_registry().descriptors():
            skill_id = descriptor.diagnosis_skill_id
            if skill_id:
                contracts[skill_id] = "DiagnosisHypothesis"
    except Exception:  # noqa: BLE001 — keep orchestration usable without registry
        pass
    return contracts


# Tests and callers may import this name; it is refreshed inside invoke paths.
SKILL_OUTPUT_CONTRACT = skill_output_contract()


class SkillInvocation(FrozenModel):
    """One audited Skill call with a validated domain contract."""

    skill_id: str
    output_contract: OutputContractName
    output: dict[str, Any]
    audit: dict[str, Any]


class SkillOrchestrator:
    """Deterministic Skill handlers bound to typed contracts."""

    def __init__(
        self,
        skills: SkillRegistry | None = None,
        *,
        strategies: CalibrationStrategyRegistry | None = None,
        expert_priors: ExpertPriorEngine | None = None,
        model: str = "deterministic",
    ) -> None:
        self.skills = skills
        self.strategies = strategies
        self.expert_priors = expert_priors
        self.model = model

    def invoke_skill(
        self,
        skill_id: str,
        *,
        diagnosis: dict[str, Any],
        view: Any | None = None,
        interpretation: EvidenceInterpretation | None = None,
        hypothesis: DiagnosisHypothesis | None = None,
        plan: CalibrationPlan | None = None,
        campaign_objective: str | None = None,
        knowledge_context: KnowledgeQueryContext | None = None,
        gate_status: str | None = None,
        qualification_status: str = "NOT_EVALUATED",
        reasons: tuple[str, ...] = (),
    ) -> SkillInvocation:
        """Activate ``skill_id``, run its contract handler, return audited output."""

        contracts = skill_output_contract()
        contract = contracts.get(skill_id)
        if contract is None:
            raise ValueError(f"skill has no typed orchestration contract: {skill_id}")

        evidence = HydrologicEvidence.from_diagnosis(diagnosis)
        diagnosis = evidence.as_diagnosis_dict()

        if skill_id == EVIDENCE_REVIEW_SKILL_ID:
            typed: FrozenModel = interpret_evidence(evidence)
        elif contracts.get(skill_id) == "DiagnosisHypothesis":
            reading = interpretation or interpret_evidence(diagnosis)
            typed = form_diagnosis_hypothesis(reading, diagnosis)
        elif skill_id == EXPERIMENT_DESIGN_SKILL_ID:
            reading = interpretation or interpret_evidence(diagnosis)
            hyp = hypothesis or form_diagnosis_hypothesis(reading, diagnosis)
            typed = plan_from_hypothesis(
                hyp,
                diagnosis,
                interpretation=reading,
                strategies=self.strategies,
                expert_priors=self.expert_priors,
                campaign_objective=campaign_objective,  # type: ignore[arg-type]
                knowledge_context=knowledge_context,
            )
        elif skill_id == RESULT_REVIEW_SKILL_ID:
            if plan is None:
                reading = interpretation or interpret_evidence(diagnosis)
                hyp = hypothesis or form_diagnosis_hypothesis(reading, diagnosis)
                plan = plan_from_hypothesis(
                    hyp,
                    diagnosis,
                    interpretation=reading,
                    strategies=self.strategies,
                    expert_priors=self.expert_priors,
                    campaign_objective=campaign_objective,  # type: ignore[arg-type]
                    knowledge_context=knowledge_context,
                )
            typed = review_experiment(
                plan,
                gate_status=str(gate_status or "KEEP"),
                qualification_status=qualification_status,
                reasons=reasons,
            )
        else:  # pragma: no cover - guarded by SKILL_OUTPUT_CONTRACT
            raise ValueError(f"unhandled orchestration skill: {skill_id}")

        audit = self._activation_audit(
            skill_id,
            view=view,
            output_contract=contract,
            output=typed.model_dump(mode="json"),
        )
        return SkillInvocation(
            skill_id=skill_id,
            output_contract=contract,
            output=typed.model_dump(mode="json"),
            audit=audit,
        )

    def plan_calibration(
        self,
        diagnosis: dict[str, Any],
        *,
        view: Any | None = None,
        campaign_objective: str | None = None,
        knowledge_context: KnowledgeQueryContext | None = None,
    ) -> tuple[CalibrationPlan, tuple[SkillInvocation, ...]]:
        """Evidence → Hypothesis → Plan through Skill invocations."""

        evidence_inv = self.invoke_skill(
            EVIDENCE_REVIEW_SKILL_ID,
            diagnosis=diagnosis,
            view=view,
        )
        interpretation = EvidenceInterpretation.model_validate(evidence_inv.output)
        invocations: list[SkillInvocation] = [evidence_inv]

        model_id = "xaj"
        if view is not None:
            model_id = str(getattr(getattr(view, "model", None), "model_id", "xaj") or "xaj")
        diagnosis = dict(diagnosis)
        diagnosis.setdefault("model_id", model_id)
        diagnosis_skill_id = None
        contracts = skill_output_contract()
        if self.skills is not None:
            candidates = self.skills._diagnosis_skill_ids(model_id)
            for skill_id in candidates:
                if skill_id in contracts:
                    diagnosis_skill_id = skill_id
                    break
        if diagnosis_skill_id is None:
            from hydro_agent.models.registry import default_model_registry

            try:
                diagnosis_skill_id = default_model_registry().diagnosis_skill_id(model_id)
            except KeyError:
                diagnosis_skill_id = None
        if diagnosis_skill_id and diagnosis_skill_id in contracts:
            hyp_inv = self.invoke_skill(
                diagnosis_skill_id,
                diagnosis=diagnosis,
                view=view,
                interpretation=interpretation,
            )
            hypothesis = DiagnosisHypothesis.model_validate(hyp_inv.output)
            invocations.append(hyp_inv)
        else:
            hypothesis = form_diagnosis_hypothesis(interpretation, diagnosis)

        plan_inv = self.invoke_skill(
            EXPERIMENT_DESIGN_SKILL_ID,
            diagnosis=diagnosis,
            view=view,
            interpretation=interpretation,
            hypothesis=hypothesis,
            campaign_objective=campaign_objective,
            knowledge_context=knowledge_context,
        )
        invocations.append(plan_inv)
        return CalibrationPlan.model_validate(plan_inv.output), tuple(invocations)

    def review_calibration(
        self,
        *,
        plan: CalibrationPlan | None = None,
        diagnosis: dict[str, Any] | None = None,
        view: Any | None = None,
        gate_status: str,
        qualification_status: str = "NOT_EVALUATED",
        reasons: tuple[str, ...] = (),
        campaign_objective: str | None = None,
        knowledge_context: KnowledgeQueryContext | None = None,
    ) -> tuple[ExperimentReview, SkillInvocation]:
        """Result-review Skill only — does not re-run the planning chain."""

        inv = self.invoke_skill(
            RESULT_REVIEW_SKILL_ID,
            diagnosis=diagnosis or {},
            view=view,
            plan=plan,
            gate_status=gate_status,
            qualification_status=qualification_status,
            reasons=reasons,
            campaign_objective=campaign_objective,
            knowledge_context=knowledge_context,
        )
        return ExperimentReview.model_validate(inv.output), inv

    def decision_audit(
        self, invocations: tuple[SkillInvocation, ...]
    ) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
        return tuple(item.skill_id for item in invocations), tuple(item.audit for item in invocations)

    def _activation_audit(
        self,
        skill_id: str,
        *,
        view: Any | None,
        output_contract: OutputContractName,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "skill_id": skill_id,
            "source": "none",
            "skill_sha256": None,
            "snapshot_sha256": None,
            "binding_sha256": None,
            "loaded_references": [],
            "output_contract": output_contract,
            "model": self.model,
            "input_evidence_ids": [],
            "output": output,
        }
        if view is not None:
            base["task_id"] = getattr(getattr(view, "task", None), "task_id", None)
            base["activation_stage"] = None
            base["input_evidence_ids"] = [
                row.evidence_id for row in getattr(view, "evidence_summary", ()) or ()
            ]

        registry = self._registry_for_view(view)
        if registry is None:
            return base

        try:
            if view is not None:
                base["activation_stage"] = registry.activation_stage(view)
            loaded = registry.get_loaded(skill_id)
            reference_paths: tuple[str, ...] | None = None
            if view is not None and loaded is not None:
                reference_paths = references_for_view(loaded, view)
            _, manifest = registry.activate_with_manifest(
                skill_id,
                reference_paths=reference_paths,
            )
        except (KeyError, ValueError):
            base["source"] = "missing"
            return base

        return {
            **base,
            **manifest,
            "output_contract": output_contract,
            "model": self.model,
            "output": output,
            "input_evidence_ids": base["input_evidence_ids"],
            "task_id": base.get("task_id"),
            "activation_stage": base.get("activation_stage"),
        }

    def _registry_for_view(self, view: Any | None) -> SkillRegistry | None:
        registry = self.skills
        if registry is None:
            return None
        if view is None or registry.repository is None:
            return registry
        snapshot = registry.freeze_for_task(view.task.task_id)
        return registry.from_snapshot(snapshot, standards=registry.standards)
