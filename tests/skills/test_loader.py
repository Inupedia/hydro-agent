from pathlib import Path

from hydro_agent.agent.contracts import (
    ActionCode,
    BudgetSummary,
    EvidenceSummary,
    HydroContext,
    ModelSummary,
    PermissionSummary,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.loader import load_skills, parse_nse_good_enough, parse_skill_md


def test_load_default_skills_from_disk():
    skills = SkillRegistry()
    ids = {s.skill_id for s in skills.list()}
    assert {"data-check", "forecast-diagnose", "xaj-calibration", "gbt-22482-accuracy"} <= ids
    assert "bounded-adapt" not in ids
    assert skills.nse_good_enough() == 0.5
    cal = skills.get("xaj-calibration")
    assert "A07_OPTIMIZE" in cal.recommended_actions
    assert cal.nse_good_enough == 0.5


def test_skill_metadata_cannot_override_standard_threshold(tmp_path: Path):
    skill_dir = tmp_path / "xaj-calibration"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: xaj-calibration
description: test calibration skill
metadata:
  nse_good_enough: "0.75"
  title_zh: "测试率定"
  recommended_actions: "A07_OPTIMIZE,A10_FREEZE"
---

# body
""",
        encoding="utf-8",
    )
    # Minimal companions so registry is usable.
    for name, title in (("data-check", "资料"), ("forecast-diagnose", "诊断")):
        d = tmp_path / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"""---
name: {name}
description: {title}
metadata:
  title_zh: "{title}"
---

# {title}
""",
            encoding="utf-8",
        )
    registry = SkillRegistry(root=tmp_path)
    # Skill hints may differ, but the GB/T DC threshold is owned by the
    # versioned knowledge repository and therefore remains 0.50.
    assert registry.get("xaj-calibration").nse_good_enough == 0.75
    assert registry.nse_good_enough() == 0.5


def test_activate_for_view_selects_calibration_when_nse_poor():
    view = WorldStateView(
        task=TaskSummary(
            task_id="t1",
            basin_id="b",
            phase="B",
            forcing_mode="R",
            allow_optimization=True,
        ),
        model=ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=SchemeSummary(scheme_id="s", status="base", content_hash="h"),
        permissions=PermissionSummary(
            safe_actions=(ActionCode.A07_OPTIMIZE, ActionCode.A10_FREEZE),
            paused=False,
        ),
        budget=BudgetSummary(
            agent_rounds_remaining=10,
            optimization_cycles_remaining=2,
            max_agent_rounds=10,
            max_optimization_cycles=2,
        ),
        evidence_summary=(
            EvidenceSummary(
                evidence_id="e1",
                action=ActionCode.A05_FORECAST,
                status="succeeded",
                new_information_hash="h1",
            ),
            EvidenceSummary(
                evidence_id="e2",
                action=ActionCode.A06_DIAGNOSE,
                status="succeeded",
                new_information_hash="h2",
                metrics={"nse": 0.2},
            ),
        ),
        latest_forecast_id="f1",
        hydro=HydroContext(diagnosis={"hypothesis": "MODEL", "metrics": {"nse": 0.2}}),
    )
    registry = SkillRegistry()
    activated = registry.activate_for_view(view)
    assert "forecast-diagnose" in activated
    assert "xaj-calibration" in activated
    assert "gbt-22482-accuracy" in activated
    rendered = registry.render_activated(view)
    assert "nse_good_enough/DC_bing=0.500" in rendered
    assert "min_scheme_grade=丙" in rendered
    assert "knowledge=GB/T 22482-2026" in rendered


def test_parse_skill_rejects_name_mismatch(tmp_path: Path):
    text = """---
name: wrong-name
description: x
---

body
"""
    try:
        parse_skill_md(text, directory_name="xaj-calibration")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "must match directory" in str(exc)


def test_parse_nse_fallback():
    assert parse_nse_good_enough({}) == 0.6
    assert parse_nse_good_enough({"nse_good_enough": "not-a-number"}) == 0.6


def test_load_skills_helper():
    loaded = load_skills()
    assert "xaj-calibration" in loaded
    assert loaded["xaj-calibration"].root is not None
