"""Agent Skills: writable advisory knowledge for Hydro-Agent.

Built-ins ship with the package; HYDRO_AGENT_SKILLS_DIR provides a writable
overlay. Skills may guide diagnosis and experiment planning, but normative
standards, Campaign locks, model constraints and Gate decisions live elsewhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.skills.loader import (
    LoadedSkill,
    default_skills_root,
    default_user_skills_root,
    load_skills,
    read_reference,
)
from hydro_agent.standards import StandardRepository

if TYPE_CHECKING:
    from hydro_agent.agent.contracts import WorldStateView

DATA_READINESS_SKILL_ID = "hydro-data-readiness"
ERROR_DIAGNOSIS_SKILL_ID = "hydro-error-diagnosis"
WATER_BALANCE_SKILL_ID = "xaj-water-balance"
RUNOFF_GENERATION_SKILL_ID = "xaj-runoff-generation"
ROUTING_DIAGNOSIS_SKILL_ID = "xaj-routing-diagnosis"
CAMPAIGN_DESIGN_SKILL_ID = "hydro-campaign-design"
EXPERIMENT_DESIGN_SKILL_ID = "hydro-experiment-design"
CALIBRATION_SKILL_ID = "xaj-calibration"
GBT_SKILL_ID = "gbt-22482-accuracy"
MODELING_PREP_SKILL_ID = "hydro-modeling-prep"
REPORT_CLOSEOUT_SKILL_ID = "hydro-report-closeout"
OPENHYDRONET_DIAGNOSIS_SKILL_ID = "openhydronet-diagnosis"
SkillSource = Literal["builtin", "user", "memory"]
ActivationStage = Literal["data", "diagnosis", "experiment", "gate", "report"]


class SkillCard(FrozenModel):
    skill_id: str
    title_zh: str
    purpose_zh: str
    when_to_use_zh: tuple[str, ...]
    required_evidence_zh: tuple[str, ...]
    recommended_actions: tuple[str, ...]
    recommended_strategies: tuple[str, ...] = ()
    stop_conditions_zh: tuple[str, ...] = ()
    counterexamples_zh: tuple[str, ...] = ()
    description: str = ""


def _card_from_loaded(skill: LoadedSkill) -> SkillCard:
    return SkillCard(
        skill_id=skill.skill_id,
        title_zh=skill.meta("title_zh", skill.name),
        purpose_zh=skill.meta("purpose_zh", skill.description),
        when_to_use_zh=skill.meta_list("when_to_use_zh"),
        required_evidence_zh=skill.meta_list("required_evidence_zh"),
        recommended_actions=skill.meta_list("recommended_actions"),
        recommended_strategies=skill.meta_list("recommended_strategies"),
        stop_conditions_zh=skill.meta_list("stop_conditions_zh"),
        counterexamples_zh=skill.meta_list("counterexamples_zh"),
        description=skill.description,
    )


class SkillRegistry:
    def __init__(
        self,
        skills: tuple[SkillCard, ...] | None = None,
        *,
        root: Path | None = None,
        builtin_root: Path | None = None,
        user_root: Path | None = None,
        loaded: dict[str, LoadedSkill] | None = None,
        standards: StandardRepository | None = None,
    ):
        self._standards = standards or StandardRepository()
        self._static = loaded is not None or skills is not None
        if root is not None:
            self._builtin_root: Path | None = None
            self._user_root = Path(root)
        else:
            self._builtin_root = (
                Path(builtin_root) if builtin_root is not None else default_skills_root()
            )
            self._user_root = (
                Path(user_root) if user_root is not None else default_user_skills_root()
            )
        self._loaded: dict[str, LoadedSkill] = {}
        self._sources: dict[str, SkillSource] = {}
        self._cards: dict[str, SkillCard] = {}
        if loaded is not None:
            self._loaded = dict(loaded)
            self._sources = {skill_id: "memory" for skill_id in self._loaded}
            self._cards = {sid: _card_from_loaded(skill) for sid, skill in self._loaded.items()}
        elif skills is not None:
            self._cards = {skill.skill_id: skill for skill in skills}
            self._sources = {skill_id: "memory" for skill_id in self._cards}
        else:
            self.reload()

    @property
    def user_root(self) -> Path:
        return self._user_root

    @property
    def builtin_root(self) -> Path | None:
        return self._builtin_root

    def reload(self) -> tuple[str, ...]:
        if self._static:
            return tuple(sorted(self._cards))
        loaded: dict[str, LoadedSkill] = {}
        sources: dict[str, SkillSource] = {}
        if self._builtin_root is not None:
            for skill_id, skill in load_skills(self._builtin_root).items():
                loaded[skill_id] = skill
                sources[skill_id] = "builtin"
        for skill_id, skill in load_skills(self._user_root).items():
            loaded[skill_id] = skill
            sources[skill_id] = "user"
        self._loaded = loaded
        self._sources = sources
        self._cards = {sid: _card_from_loaded(skill) for sid, skill in loaded.items()}
        return tuple(sorted(self._cards))

    def list(self) -> tuple[SkillCard, ...]:
        return tuple(self._cards[key] for key in sorted(self._cards))

    def get(self, skill_id: str) -> SkillCard:
        return self._cards[skill_id]

    def get_loaded(self, skill_id: str) -> LoadedSkill | None:
        return self._loaded.get(skill_id)

    def source(self, skill_id: str) -> SkillSource:
        try:
            return self._sources[skill_id]
        except KeyError as exc:
            raise KeyError(skill_id) from exc

    def summaries_zh(self) -> tuple[str, ...]:
        return tuple(f"{skill.skill_id}:{skill.title_zh}" for skill in self.list())

    def cards_for_prompt(self) -> list[dict]:
        return [skill.model_dump(mode="json") for skill in self.list()]

    @property
    def standards(self) -> StandardRepository:
        return self._standards

    def min_scheme_grade(self) -> str:
        return self._standards.min_scheme_grade()

    def gbt_accuracy_config(self, *, area_km2: float | None = None):
        return self._standards.gbt_accuracy_config(area_km2=area_km2)

    def standard_provenance(self) -> dict:
        return self._standards.provenance()

    def activate(self, skill_id: str, *, include_references: bool = True) -> str:
        skill = self._loaded.get(skill_id)
        if skill is None:
            card = self._cards.get(skill_id)
            if card is None:
                raise KeyError(skill_id)
            return f"# {card.title_zh}\n\n{card.purpose_zh}\n"
        parts = [f"# Skill: {skill.name}\n\n{skill.description}\n\n{skill.body}"]
        if include_references:
            for relative in skill.meta_list("prompt_references"):
                reference = read_reference(skill, relative)
                if reference:
                    parts.append(f"\n\n---\n\n{reference}")
        return "\n".join(parts)

    def activate_for_view(self, view: WorldStateView) -> tuple[str, ...]:
        """Select advisory Skills from state without encoding scientific stop rules.

        Stopping is intentionally absent here. A Skill may help explain evidence
        or design the next trial, but only the Campaign/ConvergencePolicy owns a
        scientific stop decision.
        """

        actions = [item.action.value for item in view.evidence_summary]
        has_forecast = bool(view.latest_forecast_id) or "A03_FORECAST" in actions
        has_diagnose = "A04_DIAGNOSE" in actions
        diagnosis = dict(view.hydro.diagnosis or {})
        hypothesis = str(diagnosis.get("hypothesis") or "").upper()
        groups = set(_name_list(diagnosis.get("recommended_param_groups")))
        has_candidate = bool(view.hydro.candidate_parameters)
        need_gate = "A05_OPTIMIZE" in actions and "A06_GATE" not in actions
        in_calibration_flow = (
            has_diagnose
            or has_candidate
            or "A05_OPTIMIZE" in actions
            or "A06_GATE" in actions
            or "A07_RESOLVE" in actions
        )

        selected: list[str] = []
        if not has_forecast:
            selected.extend(
                (
                    DATA_READINESS_SKILL_ID,
                    MODELING_PREP_SKILL_ID,
                    CAMPAIGN_DESIGN_SKILL_ID,
                )
            )
        elif not has_diagnose:
            selected.append(ERROR_DIAGNOSIS_SKILL_ID)
            if view.model.model_id == "openhydronet":
                selected.append(OPENHYDRONET_DIAGNOSIS_SKILL_ID)
        else:
            selected.append(ERROR_DIAGNOSIS_SKILL_ID)
            if view.model.model_id == "openhydronet":
                selected.append(OPENHYDRONET_DIAGNOSIS_SKILL_ID)
            else:
                if "evap" in groups:
                    selected.append(WATER_BALANCE_SKILL_ID)
                if "runoff" in groups:
                    selected.extend((WATER_BALANCE_SKILL_ID, RUNOFF_GENERATION_SKILL_ID))
                if "routing" in groups or hypothesis == "TIMING":
                    selected.append(ROUTING_DIAGNOSIS_SKILL_ID)
                if not groups and hypothesis in {"MODEL", "UNKNOWN", ""}:
                    metrics = dict(diagnosis.get("metrics") or {})
                    pbias = metrics.get("pbias_percent", metrics.get("pbias"))
                    peak_lag = metrics.get(
                        "peak_lag_hours",
                        metrics.get("peak_time_error_hours", metrics.get("peak_timing_error_hours")),
                    )
                    selected.append(WATER_BALANCE_SKILL_ID)
                    try:
                        lag_value = abs(float(peak_lag)) if peak_lag is not None else None
                    except (TypeError, ValueError):
                        lag_value = None
                    try:
                        pbias_value = abs(float(pbias)) if pbias is not None else None
                    except (TypeError, ValueError):
                        pbias_value = None
                    if lag_value is not None and lag_value >= 1.0:
                        selected.append(ROUTING_DIAGNOSIS_SKILL_ID)
                    elif pbias_value is not None and pbias_value < 10.0:
                        selected.append(RUNOFF_GENERATION_SKILL_ID)
            if view.task.allow_optimization and in_calibration_flow:
                selected.extend((CALIBRATION_SKILL_ID, EXPERIMENT_DESIGN_SKILL_ID))

        if need_gate or "A06_GATE" in actions or "A10_EVALUATE_REPORT" in actions:
            selected.append(GBT_SKILL_ID)
        if (
            view.task.phase in {"F", "E"}
            or view.hydro.campaign.stop_reason is not None
            or "A08_FREEZE" in actions
            or "A10_EVALUATE_REPORT" in actions
        ):
            selected.append(REPORT_CLOSEOUT_SKILL_ID)

        output: list[str] = []
        for skill_id in selected:
            if skill_id in self._cards and skill_id not in output:
                output.append(skill_id)
        stage = self.activation_stage(view)
        for skill_id in sorted(self._loaded):
            if self._sources.get(skill_id) != "user" or skill_id in output:
                continue
            skill = self._loaded[skill_id]
            stages = skill.meta_list("activation_stages")
            models = skill.meta_list("activation_model_ids")
            if stage in stages and (not models or view.model.model_id in models):
                output.append(skill_id)
        if not output and DATA_READINESS_SKILL_ID in self._cards:
            output.append(DATA_READINESS_SKILL_ID)
        return tuple(output)

    @staticmethod
    def activation_stage(view: WorldStateView) -> ActivationStage:
        if view.task.phase in {"F", "E"}:
            return "report"
        from hydro_agent.agent.contracts import ActionCode
        from hydro_agent.agent.permissions import (
            latest_action_index,
            pending_calibration_action,
        )

        if pending_calibration_action(view) is not None:
            return "gate"
        if view.hydro.campaign.stop_reason is not None:
            return "report"
        if latest_action_index(view, ActionCode.A07_RESOLVE) > latest_action_index(
            view, ActionCode.A04_DIAGNOSE
        ):
            return "diagnosis"
        if view.hydro.diagnosis or latest_action_index(view, ActionCode.A04_DIAGNOSE) >= 0:
            return "experiment"
        if view.latest_forecast_id or latest_action_index(view, ActionCode.A03_FORECAST) >= 0:
            return "diagnosis"
        return "data"

    def activated_for_prompt(self, view: WorldStateView) -> tuple[tuple[str, ...], str]:
        self.reload()
        skill_ids = self.activate_for_view(view)
        chunks = [self.activate(skill_id) for skill_id in skill_ids]
        provenance = self.standard_provenance()
        stop_reason = view.hydro.campaign.stop_reason
        header = (
            f"Activated skills: {', '.join(skill_ids)}. "
            f"campaign_stop_reason={stop_reason or 'none'}; "
            f"min_scheme_grade={self.min_scheme_grade()} "
            f"(standard={provenance['standard_id']}; policy={provenance['policy_id']}).\n\n"
        )
        return skill_ids, header + "\n\n====\n\n".join(chunks)

    def render_activated(self, view: WorldStateView) -> str:
        return self.activated_for_prompt(view)[1]


def _name_list(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        return tuple(item.strip() for item in raw.split(",") if item.strip())
    if isinstance(raw, (list, tuple)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()
