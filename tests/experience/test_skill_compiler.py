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



def _read_tree(root):
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_experience_skill_version_store_lifecycle(tmp_path):
    from hydro_agent.experience.skill_versions import ExperienceSkillVersionStore
    from hydro_agent.persistence.database import Database
    from hydro_agent.persistence.repository import HydroRepository
    from hydro_agent.skills import SkillRegistry

    database = Database(f"sqlite+pysqlite:///{tmp_path}/experience.db")
    database.create_schema()
    repository = HydroRepository(database)
    store = ExperienceSkillVersionStore(
        tmp_path / "experience-skill",
        repository=repository,
    )
    compiler = ExperienceSkillCompiler()

    v1 = compiler.compile(1, (entry("EXP-V1"),))
    candidate = store.create_candidate(v1)
    assert candidate.status == "candidate"

    promoted = store.promote(1)
    assert promoted.status == "promoted"
    historical_v1 = store.materialize(1)
    assert _read_tree(store.current_package) == _read_tree(historical_v1)

    registry = SkillRegistry(
        builtin_root=tmp_path / "builtin",
        agent_root=store.current_root,
        user_root=tmp_path / "user",
    )
    assert registry.source("calibration-experience") == "agent"

    v2 = compiler.compile(
        2,
        (
            entry("EXP-V1"),
            entry("EXP-V2", confidence=0.9),
        ),
    )
    store.create_candidate(v2)
    rejected = store.reject(2, "regression gate failed")
    assert rejected.status == "rejected"
    assert repository.get_current_experience_skill_version().version == 1
    assert _read_tree(store.current_package) == _read_tree(historical_v1)


def test_historical_version_materializes_after_new_promotion(tmp_path):
    from hydro_agent.experience.skill_versions import ExperienceSkillVersionStore
    from hydro_agent.persistence.database import Database
    from hydro_agent.persistence.repository import HydroRepository

    database = Database(f"sqlite+pysqlite:///{tmp_path}/history.db")
    database.create_schema()
    repository = HydroRepository(database)
    store = ExperienceSkillVersionStore(tmp_path / "store", repository=repository)
    compiler = ExperienceSkillCompiler()

    first = compiler.compile(1, (entry("EXP-ONE"),))
    second = compiler.compile(2, (entry("EXP-TWO"),))

    store.create_candidate(first)
    store.promote(1)
    v1_bytes = _read_tree(store.materialize(1))

    store.create_candidate(second)
    store.promote(2)

    assert repository.get_experience_skill_version(1).status == "superseded"
    assert repository.get_current_experience_skill_version().version == 2
    assert _read_tree(store.materialize(1)) == v1_bytes
    assert _read_tree(store.current_package) == _read_tree(store.materialize(2))
