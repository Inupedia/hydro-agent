"""Domain skills for Hydro-Agent — agentskills.io SKILL.md packages.

Progressive disclosure:
1. Metadata (name/description + machine fields) always available on WorldStateView
2. Full SKILL.md body activated in the LangGraph decide node when relevant
3. references/ loaded only when calibration needs parameter detail
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.skills.loader import (
    LoadedSkill,
    default_skills_root,
    load_skills,
    parse_nse_good_enough,
    read_reference,
)

if TYPE_CHECKING:
    from hydro_agent.agent.contracts import WorldStateView

DEFAULT_NSE_GOOD_ENOUGH = 0.5
CALIBRATION_SKILL_ID = "xaj-calibration"
GBT_SKILL_ID = "gbt-22482-accuracy"


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
    if "nse_good_enough" in skill.metadata:
        nse = parse_nse_good_enough(skill.metadata)
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
            # Backward-compatible: cards only, no bodies.
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
        """Alias for GB/T DC 丙 threshold (grade_dc_bing), with xaj-calibration fallback."""
        gbt = self._loaded.get(GBT_SKILL_ID)
        if gbt is not None:
            raw = gbt.metadata.get("grade_dc_bing") or gbt.metadata.get("nse_good_enough")
            if raw:
                try:
                    return float(raw)
                except ValueError:
                    pass
        skill = self._loaded.get(CALIBRATION_SKILL_ID)
        if skill is not None:
            return parse_nse_good_enough(skill.metadata, default=DEFAULT_NSE_GOOD_ENOUGH)
        card = self._cards.get(CALIBRATION_SKILL_ID)
        if card is not None and card.nse_good_enough is not None:
            return float(card.nse_good_enough)
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
        """Deterministic progressive disclosure for the decide node."""
        actions = [item.action.value for item in view.evidence_summary]
        has_forecast = bool(view.latest_forecast_id) or "A05_FORECAST" in actions
        has_diagnose = "A06_DIAGNOSE" in actions
        nse = _diagnosis_nse(view)
        threshold = self.nse_good_enough()
        diagnosis = dict(view.hydro.diagnosis or {})
        hypothesis = str(diagnosis.get("hypothesis") or "")
        has_candidate = bool(view.hydro.candidate_parameters)
        need_gate = "A07_OPTIMIZE" in actions and "A08_GATE" not in actions
        in_calibrate_flow = (
            need_gate
            or has_candidate
            or "A08_GATE" in actions
            or "A07_OPTIMIZE" in actions
        )
        nse_poor = nse is None or nse < threshold

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
                selected.append("xaj-calibration")
                selected.append("gbt-22482-accuracy")
            if "A08_GATE" in actions or "A12_EVALUATE_REPORT" in actions or need_gate:
                if "gbt-22482-accuracy" not in selected:
                    selected.append("gbt-22482-accuracy")

        out: list[str] = []
        for sid in selected:
            if sid in self._cards and sid not in out:
                out.append(sid)
        if not out and "data-check" in self._cards:
            out.append("data-check")
        return tuple(out)

    def render_activated(self, view: WorldStateView) -> str:
        ids = self.activate_for_view(view)
        include_params = "xaj-calibration" in ids
        chunks = [
            self.activate(sid, include_param_reference=(include_params and sid == "xaj-calibration"))
            for sid in ids
        ]
        header = (
            f"Activated skills: {', '.join(ids)}. "
            f"nse_good_enough/DC_bing={self.nse_good_enough():.3f}; "
            f"min_scheme_grade={self.min_scheme_grade()} "
            f"(from {GBT_SKILL_ID} / {CALIBRATION_SKILL_ID}).\n\n"
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
