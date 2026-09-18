from __future__ import annotations

import hashlib
import json

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.experience.contracts import ExperienceEntry
from hydro_agent.skills.loader import parse_skill_md

_SKILL_ID = "calibration-experience"
_DESCRIPTION = (
    "Uses accumulated validated hydrologic calibration experience to prioritize diagnosis "
    "and experiments. Use during model calibration diagnosis, strategy selection, and "
    "experiment planning."
)


class CompiledExperienceSkill(FrozenModel):
    files: dict[str, str]
    version: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64)


class ExperienceSkillCompiler:
    def compile(
        self,
        version: int,
        entries,
    ) -> CompiledExperienceSkill:
        if version < 1:
            raise ValueError("version must be >= 1")

        active = tuple(
            sorted(
                (entry for entry in entries if entry.status == "active"),
                key=lambda entry: (entry.experience_id, entry.revision),
            )
        )
        references = self._references(active)
        reference_paths = tuple(references)

        skill_md = self._skill_md(
            version=version,
            reference_paths=reference_paths,
        )
        files: dict[str, str] = {
            "SKILL.md": skill_md,
            **references,
            "assets/experience-schema.json": json.dumps(
                ExperienceEntry.model_json_schema(),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
        }

        parse_skill_md(
            skill_md,
            directory_name=_SKILL_ID,
        )
        canonical = json.dumps(
            files,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return CompiledExperienceSkill(
            files=files,
            version=version,
            sha256=hashlib.sha256(canonical).hexdigest(),
        )

    @staticmethod
    def _skill_md(
        *,
        version: int,
        reference_paths: tuple[str, ...],
    ) -> str:
        prompt_references = ",".join(reference_paths)
        return f"""---
name: calibration-experience
description: {_DESCRIPTION}
metadata:
  hydro-agent-source: "agent"
  hydro-agent-version: "{version}"
  activation_stages: "diagnosis,experiment"
  prompt_references: "{prompt_references}"
---

# Calibration Experience

Use this Skill as advisory decision knowledge after hydrologic diagnosis and before
experiment selection.

- Prefer rules whose scope matches the current model and basin.
- Treat cross-basin Experience as a weaker prior than same-basin Experience.
- Use negative Experience to lower the priority of repeatedly unsuccessful directions.
- Preserve hydrologically plausible exploration when evidence is uncertain or novel.
- Never write raw parameter vectors from Experience.
- Never bypass model constraints, experiment guardrails, validation gates, or final-test
  leakage protections.
- Every Experience influence must remain traceable to an Experience ID and its evidence.

Detailed rules are progressively disclosed through the declared reference files.
"""

    def _references(
        self,
        entries: tuple[ExperienceEntry, ...],
    ) -> dict[str, str]:
        files: dict[str, str] = {}

        general = tuple(
            entry
            for entry in entries
            if entry.category == "general" or not entry.scope.model_ids
        )
        files["references/general.md"] = _render_reference(
            "General Calibration Experience",
            general,
        )

        model_ids = sorted(
            {
                model_id
                for entry in entries
                for model_id in entry.scope.model_ids
            }
        )
        for model_id in model_ids:
            scoped = tuple(
                entry
                for entry in entries
                if model_id in entry.scope.model_ids
            )
            files[f"references/{model_id}.md"] = _render_reference(
                f"{model_id.upper()} Calibration Experience",
                scoped,
            )

        basin = tuple(entry for entry in entries if entry.scope.basin_ids)
        files["references/basin-experience.md"] = _render_reference(
            "Basin-specific Calibration Experience",
            basin,
        )
        return files


def _render_reference(
    title: str,
    entries: tuple[ExperienceEntry, ...],
) -> str:
    lines = [
        f"# {title}",
        "",
        "Generated from the structured Experience Store. Do not edit this compiled view manually.",
        "",
    ]
    if not entries:
        lines.append("No active Experience entries in this scope.")
        return "\n".join(lines) + "\n"

    for entry in entries:
        supporting = len(entry.supporting_evidence)
        contradicting = len(entry.contradicting_evidence)
        lines.extend(
            [
                f"## {entry.experience_id} · revision {entry.revision}",
                "",
                f"- category: {entry.category}",
                f"- confidence: {entry.confidence:.4f}",
                f"- models: {', '.join(entry.scope.model_ids) or 'all'}",
                f"- basins: {', '.join(entry.scope.basin_ids) or 'transferable'}",
                f"- supporting evidence: {supporting}",
                f"- contradicting evidence: {contradicting}",
                "- pattern:",
                "~~~json",
                json.dumps(entry.pattern, ensure_ascii=False, sort_keys=True, indent=2),
                "~~~",
                "- decision:",
                "~~~json",
                json.dumps(entry.decision, ensure_ascii=False, sort_keys=True, indent=2),
                "~~~",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
