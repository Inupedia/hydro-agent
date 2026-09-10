"""Domain skills for Hydro-Agent — agentskills.io SKILL.md packages.

Progressive disclosure:
1. metadata is always available on WorldStateView;
2. only the protocol + current hydrologic phase skills are activated for LLM decisions;
3. detailed parameter references are loaded only for XAJ calibration decisions.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.skills.loader import LoadedSkill, default_skills_root, load_skills, read_reference

if TYPE_CHECKING:
    from hydro_agent.agent.contracts import WorldStateView

DEFAULT_NSE_GOOD_ENOUGH = 0.5
CALIBRATION_PROTOCOL_SKILL_ID = "xaj-calibration-protocol"
GBT_SKILL_ID = "gbt-22482-accuracy"

_PHASE_SKILLS = {
    "P2_WATER_BALANCE": "xaj-water-balance",
    "P3_SOURCE_RECESSION": "xaj-recession-analysis",
    "P4_ROUTING_EVENT": "xaj-flood-routing",
    "P5_JOINT_REFINE": "xaj-joint-refinement",
    "P6_DEVELOPMENT_VALIDATION": "gbt-22482-accuracy",
}


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
    if raw_nse:
        try:
            nse = float(raw_nse)
        except ValueError:
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
        loaded: dict[str, LoadedSkill] | None = None,
    ):
        if loaded is not None:
            self._loaded = dict(loaded)
        elif skills is not None:
            self._loaded = {}
            self._cards = {s.skill_id: s for s in skills}
            return
        else:
            self._loaded = load_skills(root if root is not None else default_skills_root())
        self._cards = {sid: _card_from_loaded(s) for sid, s in self._loaded.items()}

    def list(self) -> tuple[SkillCard, ...]:
        return tuple(self._cards[k] for k in sorted(self._cards))

    def get(self, skill_id: str) -> SkillCard:
        return self._cards[skill_id]

    def get_loaded(self, skill_id: str) -> LoadedSkill | None:
        return self._loaded.get(skill_id)

    def summaries_zh(self) -> tuple[str, ...]:
        return tuple(f"{s.skill_id}:{s.title_zh}" for s in self.list())

    def cards_for_prompt(self) -> list[dict]:
        return [s.model_dump(mode="json") for s in self.list()]

    def nse_good_enough(self) -> float:
        gbt = self._loaded.get(GBT_SKILL_ID)
        if gbt is not None:
            raw = gbt.metadata.get("grade_dc_bing") or gbt.metadata.get("nse_good_enough")
            if raw:
                try:
                    return float(raw)
                except ValueError:
                    pass
        return DEFAULT_NSE_GOOD_ENOUGH

    def min_scheme_grade(self) -> str:
        gbt = self._loaded.get(GBT_SKILL_ID)
        if gbt is not None:
            grade = str(gbt.metadata.get("min_scheme_grade") or "丙").strip()
            if grade in {"甲", "乙", "丙"}:
                return grade
        return "丙"

    def gbt_accuracy_config(self, *, area_km2: float | None = None):
        from hydro_agent.evaluation.gbt22482 import GbtAccuracyConfig

        gbt = self._loaded.get(GBT_SKILL_ID)
        meta = dict(gbt.metadata) if gbt is not None else {}
        if "min_scheme_grade" not in meta:
            meta["min_scheme_grade"] = self.min_scheme_grade()
        if "grade_dc_bing" not in meta:
            meta["grade_dc_bing"] = str(self.nse_good_enough())
        return GbtAccuracyConfig.from_metadata(meta, area_km2=area_km2)

    def activate(self, skill_id: str, *, include_param_reference: bool = False) -> str:
        skill = self._loaded.get(skill_id)
        if skill is None:
            card = self._cards.get(skill_id)
            if card is None:
                raise KeyError(skill_id)
            return f"# {card.title_zh}\n\n{card.purpose_zh}\n"
        parts = [f"# Skill: {skill.name}\n\n{skill.description}\n\n{skill.body}"]
        if include_param_reference:
            ref = read_reference(skill, "references/xaj-parameters.md")
            if ref:
                parts.append("\n\n---\n\n" + ref)
        return "\n".join(parts)

    def activate_for_view(self, view: WorldStateView) -> tuple[str, ...]:
        actions = [item.action.value for item in view.evidence_summary]
        has_forecast = bool(view.latest_forecast_id) or "A05_FORECAST" in actions
        has_diagnose = "A06_DIAGNOSE" in actions
        phase = str(view.hydro.calibration_phase or "P2_WATER_BALANCE")

        selected: list[str] = []
        if not has_forecast:
            selected.append("data-check")
        else:
            selected.append("forecast-diagnose")

        if has_diagnose and view.task.allow_optimization and view.task.phase == "B":
            selected.append(CALIBRATION_PROTOCOL_SKILL_ID)
            phase_skill = _PHASE_SKILLS.get(phase)
            if phase_skill:
                selected.append(phase_skill)
            if phase in {
                "P3_SOURCE_RECESSION",
                "P4_ROUTING_EVENT",
                "P5_JOINT_REFINE",
                "P6_DEVELOPMENT_VALIDATION",
            }:
                selected.append("hydro-event-bank")
            if phase in {
                "P2_WATER_BALANCE",
                "P3_SOURCE_RECESSION",
                "P4_ROUTING_EVENT",
                "P5_JOINT_REFINE",
            }:
                selected.append("calibration-convergence")

        if "A08_GATE" in actions or "A12_EVALUATE_REPORT" in actions or phase == "P6_DEVELOPMENT_VALIDATION":
            selected.append(GBT_SKILL_ID)

        out: list[str] = []
        for sid in selected:
            if sid in self._cards and sid not in out:
                out.append(sid)
        if not out and "data-check" in self._cards:
            out.append("data-check")
        return tuple(out)

    def render_activated(self, view: WorldStateView) -> str:
        ids = self.activate_for_view(view)
        chunks = [
            self.activate(
                sid,
                include_param_reference=(sid == CALIBRATION_PROTOCOL_SKILL_ID),
            )
            for sid in ids
        ]
        header = (
            f"Activated skills: {', '.join(ids)}. "
            f"calibration_phase={view.hydro.calibration_phase}; "
            f"DC_bing={self.nse_good_enough():.3f}; "
            f"min_scheme_grade={self.min_scheme_grade()}.\n\n"
        )
        return header + "\n\n====\n\n".join(chunks)
