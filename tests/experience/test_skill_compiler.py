import json

from hydro_agent.experience.compiler import ExperienceSkillCompiler
from hydro_agent.experience.contracts import ExperienceEntry, ExperienceScope
from hydro_agent.skills.loader import parse_skill_md


def entry(
    experience_id,
    *,
    category="model",
    model_ids=("xaj",),
    basin_ids=(),
    confidence=0.8,
):
    return ExperienceEntry(
        experience_id=experience_id,
        revision=1,
        category=category,
        scope=ExperienceScope(model_ids=model_ids, basin_ids=basin_ids),
        pattern={"peak_bias": "negative"},
        decision={"prefer_param_groups": ["routing"]},
        supporting_evidence=(),
        contradicting_evidence=(),
        confidence=confidence,
        status="active",
    )


def test_compile_agent_skills_compliant_package():
    compiled = ExperienceSkillCompiler().compile(
        7,
        (
            entry("EXP-GENERAL", category="general", model_ids=()),
            entry("EXP-XAJ", model_ids=("xaj",)),
            entry("EXP-BASIN", model_ids=("xaj",), basin_ids=("basin-a",)),
        ),
    )

    assert {
        "SKILL.md",
        "references/general.md",
        "references/xaj.md",
        "references/basin-experience.md",
        "assets/experience-schema.json",
    } <= set(compiled.files)

    loaded = parse_skill_md(
        compiled.files["SKILL.md"],
        directory_name="calibration-experience",
    )
    assert loaded.name == "calibration-experience"
    assert loaded.meta("hydro-agent-source") == "agent"
    assert loaded.meta("hydro-agent-version") == "7"
    assert loaded.meta_list("activation_stages") == ("diagnosis", "experiment")
    assert "references/xaj.md" in loaded.meta_list("prompt_references")
    assert "EXP-XAJ" in compiled.files["references/xaj.md"]
    assert "EXP-BASIN" in compiled.files["references/basin-experience.md"]
    json.loads(compiled.files["assets/experience-schema.json"])


def test_compile_is_deterministic_for_same_state():
    compiler = ExperienceSkillCompiler()
    entries = (
        entry("EXP-B", basin_ids=("basin-b",)),
        entry("EXP-A", confidence=0.7),
    )

    first = compiler.compile(2, entries)
    second = compiler.compile(2, tuple(reversed(entries)))

    assert first.files == second.files
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64


def test_inactive_experience_is_not_compiled():
    active = entry("EXP-ACTIVE")
    inactive = entry("EXP-OLD").model_copy(update={"status": "superseded"})

    compiled = ExperienceSkillCompiler().compile(3, (inactive, active))

    assert "EXP-ACTIVE" in compiled.files["references/xaj.md"]
    assert "EXP-OLD" not in compiled.files["references/xaj.md"]
