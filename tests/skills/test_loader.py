from pathlib import Path

from hydro_agent.agent import contracts
from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.loader import load_skills, parse_skill_md


EXPECTED_SKILLS = {
    "hydro-data-readiness",
    "hydro-error-diagnosis",
    "xaj-water-balance",
    "xaj-runoff-generation",
    "xaj-routing-diagnosis",
    "hydro-campaign-design",
    "hydro-experiment-design",
    "xaj-calibration",
    "gbt-22482-accuracy",
}


def test_load_default_skills_from_disk():
    skills = SkillRegistry()
    ids = {s.skill_id for s in skills.list()}
    assert EXPECTED_SKILLS <= ids
    assert "data-check" not in ids
    assert "forecast-diagnose" not in ids
    cal = skills.get("xaj-calibration")
    assert "A07_OPTIMIZE" in cal.recommended_actions
    assert "hydro-experiment-design" in ids


def test_activate_for_view_uses_process_skills_without_nse_stop_threshold():
    view = contracts.WorldStateView(
        task=contracts.TaskSummary(
            task_id="t1",
            basin_id="b",
            phase="B",
            forcing_mode="R",
            allow_optimization=True,
        ),
        model=contracts.ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=contracts.SchemeSummary(scheme_id="s", status="base", content_hash="h"),
        permissions=contracts.PermissionSummary(
            safe_actions=(contracts.ActionCode.A07_OPTIMIZE, contracts.ActionCode.A10_FREEZE),
            paused=False,
        ),
        budget=contracts.BudgetSummary(
            agent_rounds_remaining=10,
            optimization_cycles_remaining=2,
            max_agent_rounds=10,
            max_optimization_cycles=2,
        ),
        evidence_summary=(
            contracts.EvidenceSummary(
                evidence_id="e1",
                action=contracts.ActionCode.A05_FORECAST,
                status="succeeded",
                new_information_hash="h1",
            ),
            contracts.EvidenceSummary(
                evidence_id="e2",
                action=contracts.ActionCode.A06_DIAGNOSE,
                status="succeeded",
                new_information_hash="h2",
                metrics={"nse": 0.8},
            ),
        ),
        latest_forecast_id="f1",
        hydro=contracts.HydroContext(
            diagnosis={
                "hypothesis": "TIMING",
                "metrics": {"nse": 0.8},
                "recommended_param_groups": ["routing"],
            }
        ),
    )
    registry = SkillRegistry()
    activated = registry.activate_for_view(view)
    assert "hydro-error-diagnosis" in activated
    assert "xaj-routing-diagnosis" in activated
    assert "xaj-calibration" in activated
    assert "hydro-experiment-design" in activated
    assert "xaj-water-balance" not in activated
    rendered = registry.render_activated(view)
    assert "campaign_stop_reason=none" in rendered
    assert "nse_good_enough" not in rendered
    assert "standard=GB/T 22482-2026" in rendered


def test_prompt_references_are_loaded_from_metadata():
    registry = SkillRegistry()
    rendered = registry.activate("xaj-routing-diagnosis")
    assert "退水与滞后" in rendered
    assert "Validator" in rendered


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


def test_load_skills_helper():
    loaded = load_skills()
    assert EXPECTED_SKILLS <= set(loaded)
    assert loaded["xaj-calibration"].root is not None
