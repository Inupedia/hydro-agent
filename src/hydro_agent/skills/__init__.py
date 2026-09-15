"""Agent Skills: writable advisory knowledge for Hydro-Agent.

Built-ins ship with the package; HYDRO_AGENT_SKILLS_DIR provides a writable
overlay. Skills may guide diagnosis and experiment planning, but normative
standards, protocol locks, model constraints and Gate decisions live elsewhere.
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

CALIBRATION_SKILL_ID = "xaj-calibration"
GBT_SKILL_ID = "gbt-22482-accuracy"
DEFAULT_NSE_GOOD_ENOUGH = float(StandardRepository().gbt_accuracy_metadata()["grade_dc_bing"])
SkillSource = Literal["builtin", "user", "memory"]


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
    nse_good_enough: float | None = None


def _card_from_loaded(skill: LoadedSkill) -> SkillCard:
    nse = None
    raw_nse = skill.metadata.get("nse_good_enough")
    if raw_nse is not None:
        try:
            nse = float(raw_nse)
        except (TypeError, ValueError):
            nse = None
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
        nse_good_enough=nse,
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
            self._builtin_root = Path(builtin_root) if builtin_root is not None else default_skills_root()
            self._user_root = Path(user_root) if user_root is not None else default_user_skills_root()
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

    def nse_good_enough(self) -> float:
        return float(self._standards.gbt_accuracy_metadata()["grade_dc_bing"])

    def min_scheme_grade(self) -> str:
        grade = str(self._standards.gate_defaults().get("min_scheme_grade") or "丙").strip()
        if grade not in {"甲", "乙", "丙"}:
            raise ValueError(f"invalid standard policy min_scheme_grade: {grade}")
        return grade

    def gbt_accuracy_config(self, *, area_km2: float | None = None):
        from hydro_agent.evaluation.gbt22482 import GbtAccuracyConfig

        meta = self._standards.gbt_accuracy_metadata(area_km2=area_km2)
        return GbtAccuracyConfig.from_metadata(meta, area_km2=area_km2)

    def standard_provenance(self) -> dict:
        return self._standards.provenance()

    def activate(self, skill_id: str, *, include_param_reference: bool = False) -> str:
        skill = self._loaded.get(skill_id)
        if skill is None:
            card = self._cards.get(skill_id)
            if card is None:
                raise KeyError(skill_id)
            return f"# {card.title_zh}\n\n{card.purpose_zh}\n"
        parts = [f"# Skill: {skill.name}\n\n{skill.description}\n\n{skill.body}"]
        if include_param_reference:
            reference = read_reference(skill, "references/xaj-parameters.md")
            if reference:
                parts.append("\n\n---\n\n" + reference)
        return "\n".join(parts)

    def activate_for_view(self, view: WorldStateView) -> tuple[str, ...]:
        actions = [item.action.value for item in view.evidence_summary]
        has_forecast = bool(view.latest_forecast_id) or "A05_FORECAST" in actions
        has_diagnose = "A06_DIAGNOSE" in actions
        nse = _diagnosis_nse(view)
        diagnosis = dict(view.hydro.diagnosis or {})
        hypothesis = str(diagnosis.get("hypothesis") or "")
        has_candidate = bool(view.hydro.candidate_parameters)
        need_gate = "A07_OPTIMIZE" in actions and "A08_GATE" not in actions
        in_calibrate_flow = need_gate or has_candidate or "A08_GATE" in actions or "A07_OPTIMIZE" in actions
        nse_poor = nse is None or nse < self.nse_good_enough()
        selected: list[str] = []
        if not has_forecast:
            selected.append("data-check")
        elif not has_diagnose:
            selected.append("forecast-diagnose")
        else:
            selected.append("forecast-diagnose")
            if in_calibrate_flow or (
                view.task.allow_optimization
                and nse_poor
                and (hypothesis in {"", "MODEL", "UNKNOWN", "TIMING"} or nse is not None)
            ):
                selected.extend(("xaj-calibration", "gbt-22482-accuracy"))
            if "A08_GATE" in actions or "A12_EVALUATE_REPORT" in actions or need_gate:
                if "gbt-22482-accuracy" not in selected:
                    selected.append("gbt-22482-accuracy")
        output: list[str] = []
        for skill_id in selected:
            if skill_id in self._cards and skill_id not in output:
                output.append(skill_id)
        if not output and "data-check" in self._cards:
            output.append("data-check")
        return tuple(output)

    def render_activated(self, view: WorldStateView) -> str:
        self.reload()
        skill_ids = self.activate_for_view(view)
        chunks = [
            self.activate(skill_id, include_param_reference=(skill_id == "xaj-calibration"))
            for skill_id in skill_ids
        ]
        provenance = self.standard_provenance()
        header = (
            f"Activated skills: {', '.join(skill_ids)}. "
            f"nse_good_enough/DC_bing={self.nse_good_enough():.3f}; "
            f"min_scheme_grade={self.min_scheme_grade()} "
            f"(standard={provenance['standard_id']}; policy={provenance['policy_id']}).\n\n"
        )
        return header + "\n\n====\n\n".join(chunks)


def _diagnosis_nse(view: WorldStateView) -> float | None:
    diagnosis = dict(view.hydro.diagnosis or {})
    metrics = diagnosis.get("metrics") if isinstance(diagnosis.get("metrics"), dict) else {}
    raw = metrics.get("nse")
    if raw is None:
        raw = diagnosis.get("nse")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return value
