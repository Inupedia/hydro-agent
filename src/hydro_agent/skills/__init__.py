"""Agent Skills: writable advisory knowledge for Hydro-Agent.

Built-ins ship with the package; HYDRO_AGENT_SKILLS_DIR provides a writable
overlay. Skills may guide diagnosis and experiment planning, but normative
standards, Campaign locks, model constraints and Gate decisions live elsewhere.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.skills.binding import read_binding
from hydro_agent.skills.loader import (
    LoadedSkill,
    default_skills_root,
    default_user_skills_root,
    load_skill_content,
    load_skills,
    parse_skill_md,
    parse_skill_metadata_text,
    read_reference,
)
from hydro_agent.skills.reference_policy import references_for_view
from hydro_agent.skills.snapshot import (
    build_snapshot,
    capture_package,
    snapshot_file_bytes,
    verify_snapshot,
)
from hydro_agent.standards import StandardRepository

if TYPE_CHECKING:
    from hydro_agent.agent.contracts import WorldStateView

DATA_REVIEW_SKILL_ID = "hydrology-data-review"
EVIDENCE_REVIEW_SKILL_ID = "hydrologic-evidence-review"
XAJ_DIAGNOSIS_SKILL_ID = "xaj-calibration-diagnosis"
GR4J_DIAGNOSIS_SKILL_ID = "gr4j-calibration-diagnosis"
EXPERIMENT_DESIGN_SKILL_ID = "calibration-experiment-design"
RESULT_REVIEW_SKILL_ID = "calibration-result-review"
REPORTING_SKILL_ID = "hydrology-reporting"
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
        repository=None,
    ):
        self._standards = standards or StandardRepository()
        self.repository = repository
        self._snapshot_files: dict[str, dict] = {}
        self._snapshot_bindings: dict[str, dict] = {}
        self._snapshot_sha256: str | None = None
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

    def binding_for(self, skill_id: str) -> dict:
        skill = self._loaded.get(skill_id)
        if skill is None:
            raise KeyError(skill_id)
        if skill_id in self._snapshot_bindings:
            return self._snapshot_bindings[skill_id]
        if self._sources.get(skill_id) == "user":
            binding = read_binding(self._user_root, skill_id)
            if binding is not None:
                return binding
        if self._builtin_root is not None:
            binding = read_binding(self._builtin_root, skill_id)
            if binding is not None:
                return binding
        return {
            "activation_stages": list(skill.meta_list("activation_stages")),
            "activation_model_ids": list(skill.meta_list("activation_model_ids")),
        }

    def freeze_for_task(self, task_id: str) -> dict:
        if self.repository is None:
            raise ValueError("Skill Registry needs a repository to freeze a task")
        existing = self.repository.get_task_state(task_id).skill_snapshot_json
        if existing is not None:
            verify_snapshot(existing)
            return existing
        self.reload()
        packages: dict[str, dict] = {}
        for skill_id, skill in sorted(self._loaded.items()):
            if skill.root is None:
                continue
            packages[skill_id] = {
                "source": self.source(skill_id),
                "binding": self.binding_for(skill_id),
                "files": capture_package(skill.root),
            }
        snapshot = build_snapshot(packages)
        self.repository.set_skill_snapshot(task_id, snapshot)
        return snapshot

    @classmethod
    def from_snapshot(cls, snapshot: dict, *, standards: StandardRepository | None = None):
        verify_snapshot(snapshot)
        loaded: dict[str, LoadedSkill] = {}
        for skill_id, package in snapshot["skills"].items():
            raw = snapshot_file_bytes(package["files"], "SKILL.md").decode("utf-8")
            loaded[skill_id] = parse_skill_metadata_text(raw, directory_name=skill_id)
        registry = cls(loaded=loaded, standards=standards)
        registry._sources = {
            skill_id: package["source"] for skill_id, package in snapshot["skills"].items()
        }
        registry._snapshot_files = {
            skill_id: package["files"] for skill_id, package in snapshot["skills"].items()
        }
        registry._snapshot_bindings = {
            skill_id: package["binding"] for skill_id, package in snapshot["skills"].items()
        }
        registry._snapshot_sha256 = snapshot["sha256"]
        return registry

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
        return self.activate_with_manifest(skill_id, include_references=include_references)[0]

    def activate_with_manifest(
        self,
        skill_id: str,
        *,
        include_references: bool = True,
        reference_paths: tuple[str, ...] | None = None,
    ) -> tuple[str, dict]:
        skill = self._loaded.get(skill_id)
        if skill is None:
            card = self._cards.get(skill_id)
            if card is None:
                raise KeyError(skill_id)
            return f"# {card.title_zh}\n\n{card.purpose_zh}\n", {
                "skill_id": skill_id,
                "source": self.source(skill_id),
                "skill_sha256": None,
                "snapshot_sha256": self._snapshot_sha256,
                "loaded_references": [],
            }
        if skill_id in self._snapshot_files:
            raw = snapshot_file_bytes(self._snapshot_files[skill_id], "SKILL.md").decode("utf-8")
            skill = parse_skill_md(raw, directory_name=skill_id)
        else:
            skill = load_skill_content(skill)
        parts = [f"# Skill: {skill.name}\n\n{skill.description}\n\n{skill.body}"]
        references: list[dict[str, str]] = []
        if include_references:
            declared = skill.meta_list("prompt_references")
            requested = declared if reference_paths is None else reference_paths
            if any(relative not in declared for relative in requested):
                raise ValueError(f"undeclared Skill reference requested: {skill_id}")
            for relative in requested:
                if skill_id in self._snapshot_files:
                    files = self._snapshot_files[skill_id]
                    if relative not in files:
                        continue
                    raw = snapshot_file_bytes(files, relative)
                    reference = raw.decode("utf-8")
                    if len(reference) > 4000:
                        reference = reference[:3980] + "\n\n…(truncated)…"
                    reference_hash = hashlib.sha256(raw).hexdigest()
                else:
                    reference = read_reference(skill, relative)
                    reference_hash = (
                        hashlib.sha256((skill.root / relative).read_bytes()).hexdigest()
                        if skill.root is not None and reference
                        else ""
                    )
                if reference:
                    parts.append(f"\n\n---\n\n{reference}")
                    references.append({
                        "path": relative,
                        "sha256": reference_hash,
                    })
        manifest = {
            "skill_id": skill_id,
            "source": self.source(skill_id),
            "skill_sha256": hashlib.sha256(skill.raw_text.encode("utf-8")).hexdigest(),
            "snapshot_sha256": self._snapshot_sha256,
            "binding_sha256": hashlib.sha256(
                json.dumps(self.binding_for(skill_id), sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest(),
            "loaded_references": references,
        }
        return "\n".join(parts), manifest

    def activate_for_view(self, view: WorldStateView) -> tuple[str, ...]:
        """Select advisory Skills from state without encoding scientific stop rules.

        Stopping is intentionally absent here. A Skill may help explain evidence
        or design the next trial, but only the Campaign/ConvergencePolicy owns a
        scientific stop decision.
        """

        actions = {item.action.value for item in view.evidence_summary}
        has_forecast = bool(view.latest_forecast_id) or "A03_FORECAST" in actions
        has_diagnosis = bool(view.hydro.diagnosis) or "A04_DIAGNOSE" in actions
        stage = self.activation_stage(view)
        selected: list[str] = []
        if stage == "report":
            if "A06_GATE" in actions or "A10_EVALUATE_REPORT" in actions:
                selected.append(RESULT_REVIEW_SKILL_ID)
            selected.append(REPORTING_SKILL_ID)
        elif stage == "data" or not has_forecast:
            selected.append(DATA_REVIEW_SKILL_ID)
            if view.task.allow_optimization:
                selected.append(EXPERIMENT_DESIGN_SKILL_ID)
        elif stage == "gate":
            selected.append(RESULT_REVIEW_SKILL_ID)
        else:
            selected.append(EVIDENCE_REVIEW_SKILL_ID)
            if has_diagnosis:
                for skill_id in self._diagnosis_skill_ids(view.model.model_id):
                    selected.append(skill_id)
            if has_diagnosis and view.task.allow_optimization:
                selected.append(EXPERIMENT_DESIGN_SKILL_ID)
            if "A06_GATE" in actions or "A07_RESOLVE" in actions:
                selected.append(RESULT_REVIEW_SKILL_ID)

        output: list[str] = []
        for skill_id in selected:
            if skill_id not in self._cards or skill_id in output:
                continue
            if skill_id not in self._loaded:
                output.append(skill_id)
                continue
            binding = self.binding_for(skill_id)
            stages = binding["activation_stages"]
            models = binding["activation_model_ids"]
            if stage in stages and (not models or view.model.model_id in models):
                output.append(skill_id)
        for skill_id in sorted(self._loaded):
            if self._sources.get(skill_id) != "user" or skill_id in output:
                continue
            binding = self.binding_for(skill_id)
            stages = binding["activation_stages"]
            models = binding["activation_model_ids"]
            if stage in stages and (not models or view.model.model_id in models):
                output.append(skill_id)
        if not output and DATA_REVIEW_SKILL_ID in self._cards:
            output.append(DATA_REVIEW_SKILL_ID)
        return tuple(output)

    def _diagnosis_skill_ids(self, model_id: str) -> tuple[str, ...]:
        """Resolve model diagnosis Skills from bindings / plugin descriptor — not if/elif."""

        from hydro_agent.models.registry import default_model_registry

        preferred: list[str] = []
        try:
            skill_id = default_model_registry().diagnosis_skill_id(model_id)
        except KeyError:
            skill_id = None
        if skill_id:
            preferred.append(skill_id)
        for skill_id in sorted(self._loaded):
            if skill_id in preferred:
                continue
            binding = self.binding_for(skill_id)
            stages = binding.get("activation_stages") or []
            models = binding.get("activation_model_ids") or []
            if "diagnosis" in stages and model_id in models:
                preferred.append(skill_id)
        return tuple(preferred)

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
        skill_ids, prompt, _ = self.activated_for_prompt_with_audit(view)
        return skill_ids, prompt

    def activated_for_prompt_with_audit(
        self, view: WorldStateView
    ) -> tuple[tuple[str, ...], str, tuple[dict, ...]]:
        if self.repository is not None:
            snapshot = self.freeze_for_task(view.task.task_id)
            frozen = self.from_snapshot(snapshot, standards=self._standards)
            return frozen.activated_for_prompt_with_audit(view)
        self.reload()
        skill_ids = self.activate_for_view(view)
        activations = [
            self.activate_with_manifest(
                skill_id,
                reference_paths=references_for_view(self._loaded[skill_id], view)
                if skill_id in self._loaded
                else (),
            )
            for skill_id in skill_ids
        ]
        chunks = [item[0] for item in activations]
        provenance = self.standard_provenance()
        stop_reason = view.hydro.campaign.stop_reason
        header = (
            f"Activated skills: {', '.join(skill_ids)}. "
            f"campaign_stop_reason={stop_reason or 'none'}; "
            f"min_scheme_grade={self.min_scheme_grade()} "
            f"(standard={provenance['standard_id']}; policy={provenance['policy_id']}).\n\n"
        )
        return (
            skill_ids,
            header + "\n\n====\n\n".join(chunks),
            tuple(
                {
                    **item[1],
                    "task_id": view.task.task_id,
                    "activation_stage": self.activation_stage(view),
                    "input_evidence_ids": [row.evidence_id for row in view.evidence_summary],
                }
                for item in activations
            ),
        )

    def render_activated(self, view: WorldStateView) -> str:
        return self.activated_for_prompt(view)[1]
