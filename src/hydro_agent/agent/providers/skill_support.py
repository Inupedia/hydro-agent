"""Shared Skill/context helpers for decision providers."""

from __future__ import annotations

import json

from hydro_agent.agent.contracts import WorldStateView
from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.expert import ExpertPriorEngine
from hydro_agent.skills.governance import KnowledgeQueryContext
from hydro_agent.skills.orchestration import SkillOrchestrator


def diagnosis_from_view(view: WorldStateView) -> dict:
    diagnosis = dict(view.hydro.diagnosis or {})
    raw_hypotheses = diagnosis.get("hypotheses_json")
    if isinstance(raw_hypotheses, str) and raw_hypotheses:
        try:
            diagnosis["hypotheses"] = json.loads(raw_hypotheses)
        except json.JSONDecodeError:
            diagnosis["hypotheses"] = []
    return diagnosis


def knowledge_context_from_view(view: WorldStateView) -> KnowledgeQueryContext:
    return KnowledgeQueryContext(
        model_id=str(view.model.model_id),
        basin_id=view.task.basin_id,
        allow_unverified_expert_priors=view.hydro.allow_unverified_expert_priors,
        forbidden_evidence_dataset_ids=view.hydro.forbidden_evidence_dataset_ids,
    )


def expert_priors_for_task(
    skills: SkillRegistry | None, task_id: str
) -> ExpertPriorEngine | None:
    repository = getattr(skills, "repository", None) if skills is not None else None
    if repository is None:
        return None
    snapshot = repository.get_task_state(task_id).skill_snapshot_json
    return ExpertPriorEngine(snapshot=snapshot) if snapshot is not None else None


def skill_orchestrator(
    skills: SkillRegistry | None,
    *,
    task_id: str,
    model: str,
) -> SkillOrchestrator:
    return SkillOrchestrator(
        skills,
        expert_priors=expert_priors_for_task(skills, task_id),
        model=model,
    )
