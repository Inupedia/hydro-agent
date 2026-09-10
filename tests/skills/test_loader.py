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
    assert {
        "data-check",
        "forecast-diagnose",
        "xaj-calibration-protocol",
        "xaj-water-balance",
        "gbt-22482-accuracy",
    } <= ids
    assert "xaj-calibration" not in ids
    assert "bounded-adapt" not in ids
    assert skills.nse_good_enough() == 0.5
    protocol = skills.get("xaj-calibration-protocol")
    assert "A07_OPTIMIZE" in protocol.recommended_actions


def test_nse_good_enough_follows_gbt_metadata(tmp_path: Path):
    for name, title, metadata in (
        ("data-check", "资料", ""),
        ("forecast-diagnose", "诊断", ""),
        (
            "gbt-22482-accuracy",
            "GB/T",
            '  grade_dc_bing: "0.75"\n  min_scheme_grade: "丙"\n',
        ),
    ):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "SKILL.md").write_text(
            f"""---
name: {name}
description: {title}
metadata:
  title_zh: "{title}"
{metadata}---

# {title}
""",
            encoding="utf-8",
        )
    registry = SkillRegistry(root=tmp_path)
    assert registry.nse_good_enough() == 0.75


def test_activate_for_view_selects_phase_protocol_after_diagnosis():
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
        hydro=HydroContext(
            calibration_phase="P2_WATER_BALANCE",
            diagnosis={"hypothesis": "MODEL", "metrics": {"nse": 0.2}},
        ),
    )
    registry = SkillRegistry()
    activated = registry.activate_for_view(view)
    assert "forecast-diagnose" in activated
    assert "xaj-calibration-protocol" in activated
    assert "xaj-water-balance" in activated
    assert "calibration-convergence" in activated
    assert "xaj-calibration" not in activated
    rendered = registry.render_activated(view)
    assert "calibration_phase=P2_WATER_BALANCE" in rendered
    assert "DC_bing=0.500" in rendered
    assert "min_scheme_grade=丙" in rendered


def test_parse_skill_rejects_name_mismatch(tmp_path: Path):
    text = """---
name: wrong-name
description: x
---

body
"""
    try:
        parse_skill_md(text, directory_name="xaj-calibration-protocol")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "must match directory" in str(exc)


def test_parse_nse_fallback():
    assert parse_nse_good_enough({}) == 0.6
    assert parse_nse_good_enough({"nse_good_enough": "not-a-number"}) == 0.6


def test_load_skills_helper():
    loaded = load_skills()
    assert "xaj-calibration-protocol" in loaded
    assert "xaj-calibration" not in loaded
    assert loaded["xaj-calibration-protocol"].root is not None
