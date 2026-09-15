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
    "hydro-modeling-prep",
    "hydro-report-closeout",
    "openhydronet-diagnosis",
}


def test_load_default_skills_from_disk():
    skills = SkillRegistry()
    ids = {s.skill_id for s in skills.list()}
    assert EXPECTED_SKILLS <= ids
    assert "data-check" not in ids
    assert "forecast-diagnose" not in ids
    cal = skills.get("xaj-calibration")
    assert "A05_OPTIMIZE" in cal.recommended_actions
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
            safe_actions=(contracts.ActionCode.A05_OPTIMIZE, contracts.ActionCode.A08_FREEZE),
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
                action=contracts.ActionCode.A03_FORECAST,
                status="succeeded",
                new_information_hash="h1",
            ),
            contracts.EvidenceSummary(
                evidence_id="e2",
                action=contracts.ActionCode.A04_DIAGNOSE,
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


def test_data_stage_activates_campaign_and_modeling_skills():
    view = contracts.WorldStateView(
        task=contracts.TaskSummary(task_id="t1", basin_id="b", phase="B", forcing_mode="R"),
        model=contracts.ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=contracts.SchemeSummary(scheme_id="s", status="base", content_hash="h"),
        permissions=contracts.PermissionSummary(safe_actions=(contracts.ActionCode.A02_VALIDATE_SCHEME,)),
        budget=contracts.BudgetSummary(
            agent_rounds_remaining=10,
            optimization_cycles_remaining=2,
            max_agent_rounds=10,
            max_optimization_cycles=2,
        ),
    )
    activated = SkillRegistry().activate_for_view(view)
    assert "hydro-data-readiness" in activated
    assert "hydro-campaign-design" in activated
    assert "hydro-modeling-prep" in activated


def test_unknown_hypothesis_prefers_water_balance_over_full_fanout():
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
            safe_actions=(contracts.ActionCode.A05_OPTIMIZE,),
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
                action=contracts.ActionCode.A03_FORECAST,
                status="succeeded",
                new_information_hash="h1",
            ),
            contracts.EvidenceSummary(
                evidence_id="e2",
                action=contracts.ActionCode.A04_DIAGNOSE,
                status="succeeded",
                new_information_hash="h2",
            ),
        ),
        latest_forecast_id="f1",
        hydro=contracts.HydroContext(
            diagnosis={
                "hypothesis": "UNKNOWN",
                "metrics": {"nse": 0.2, "pbias_percent": 3.0},
                "recommended_param_groups": [],
            }
        ),
    )
    activated = SkillRegistry().activate_for_view(view)
    assert "xaj-water-balance" in activated
    assert "xaj-runoff-generation" in activated
    assert "xaj-routing-diagnosis" not in activated


def test_user_skill_activates_only_in_declared_stage_and_model(tmp_path: Path):
    user_dir = tmp_path / "user" / "hydro-peak-timing"
    user_dir.mkdir(parents=True)
    (user_dir / "SKILL.md").write_text(
        """---
name: hydro-peak-timing
description: Explain peak timing evidence.
metadata:
  activation_stages: "diagnosis|experiment"
  activation_model_ids: "xaj"
---

# Peak timing guidance
""",
        encoding="utf-8",
    )
    registry = SkillRegistry(user_root=tmp_path / "user")
    base = contracts.WorldStateView(
        task=contracts.TaskSummary(task_id="t1", basin_id="b", phase="B", forcing_mode="R"),
        model=contracts.ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=contracts.SchemeSummary(scheme_id="s", status="base", content_hash="h"),
        permissions=contracts.PermissionSummary(safe_actions=(contracts.ActionCode.A04_DIAGNOSE,)),
        budget=contracts.BudgetSummary(
            agent_rounds_remaining=10,
            optimization_cycles_remaining=2,
            max_agent_rounds=10,
            max_optimization_cycles=2,
        ),
    )
    assert "hydro-peak-timing" not in registry.activate_for_view(base)
    diagnosed = base.model_copy(update={"latest_forecast_id": "f1"})
    ids, prompt = registry.activated_for_prompt(diagnosed)
    assert "hydro-peak-timing" in ids
    assert "# Peak timing guidance" in prompt
    other_model = diagnosed.model_copy(
        update={"model": contracts.ModelSummary(model_id="openhydronet", capabilities=("forecast",))}
    )
    assert "hydro-peak-timing" not in registry.activate_for_view(other_model)


def test_frontmatter_json_quoted_text_preserves_quotes_and_newlines():
    parsed = parse_skill_md(
        '---\nname: quoted-skill\ndescription: "Peak \\"timing\\" notes"\n'
        'metadata:\n  title_zh: "洪峰\\n时滞"\n---\n\n# Guidance\n',
        directory_name="quoted-skill",
    )
    assert parsed.description == 'Peak "timing" notes'
    assert parsed.meta("title_zh") == "洪峰\n时滞"


def test_pending_candidate_uses_gate_stage_even_when_campaign_budget_is_exhausted():
    view = contracts.WorldStateView(
        task=contracts.TaskSummary(task_id="t1", basin_id="b", phase="B", forcing_mode="R"),
        model=contracts.ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=contracts.SchemeSummary(scheme_id="s", status="base", content_hash="h"),
        permissions=contracts.PermissionSummary(safe_actions=(contracts.ActionCode.A06_GATE,)),
        budget=contracts.BudgetSummary(
            agent_rounds_remaining=10,
            optimization_cycles_remaining=1,
            max_agent_rounds=10,
            max_optimization_cycles=2,
        ),
        evidence_summary=(
            contracts.EvidenceSummary(
                evidence_id="e1",
                action=contracts.ActionCode.A05_OPTIMIZE,
                status="succeeded",
                new_information_hash="h1",
            ),
        ),
        hydro=contracts.HydroContext(
            campaign={"mode": "smoke", "stop_reason": "BUDGET_EXHAUSTED"}
        ),
    )
    assert SkillRegistry.activation_stage(view) == "gate"


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
