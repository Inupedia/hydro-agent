from datetime import date

from hydro_agent.optimization.strategies import CalibrationStrategyRegistry
from hydro_agent.skills import SkillRegistry
from hydro_agent.workbench.validation_gate import diagnose_forecast_errors


def test_strategy_registry_exposes_distinct_experiment_strategies():
    registry = CalibrationStrategyRegistry()
    assert set(registry.list_ids()) >= {
        "xaj-bounded-v1",
        "xaj-peak-bias-v1",
        "xaj-local-refine-v1",
        "xaj-hydrologist-manual-v1",
    }
    assert registry.get("xaj-bounded-v1").random_seed != registry.get("xaj-peak-bias-v1").random_seed
    assert registry.get("xaj-local-refine-v1").local_scale == 0.25


def test_skills_registry_exposes_hydrologist_protocol_modules():
    skills = SkillRegistry()
    ids = {s.skill_id for s in skills.list()}
    assert {
        "data-check",
        "forecast-diagnose",
        "xaj-calibration-protocol",
        "xaj-water-balance",
        "xaj-recession-analysis",
        "xaj-flood-routing",
        "xaj-joint-refinement",
        "hydro-event-bank",
        "calibration-convergence",
        "gbt-22482-accuracy",
    } <= ids
    assert "xaj-calibration" not in ids
    assert "A06_DIAGNOSE" in skills.get("forecast-diagnose").recommended_actions
    assert "A07_OPTIMIZE" in skills.get("xaj-calibration-protocol").recommended_actions
    assert skills.nse_good_enough() == 0.5
    assert skills.min_scheme_grade() == "丙"


def test_diagnose_recommends_peak_strategy_on_underestimation():
    truth = {
        date(2020, 5, 2): 100.0,
        date(2020, 5, 3): 120.0,
        date(2020, 5, 4): 90.0,
    }
    result = diagnose_forecast_errors(
        truth=truth,
        lead_values={1: 40.0, 2: 45.0, 3: 42.0},
        issue_day=date(2020, 5, 1),
        nse_good_enough=0.6,
    )
    assert result["hypothesis"] == "MODEL"
    assert result["recommended_strategy_id"] == "xaj-peak-bias-v1"
    assert result["recommended_param_groups"] == ["runoff", "routing"]
    assert result["recommended_objective"] == "composite"


def test_diagnose_freeze_uses_skill_threshold():
    truth = {
        date(2020, 5, 2): 100.0,
        date(2020, 5, 3): 101.0,
        date(2020, 5, 4): 99.0,
    }
    result = diagnose_forecast_errors(
        truth=truth,
        lead_values={1: 100.0, 2: 101.0, 3: 99.0},
        issue_day=date(2020, 5, 1),
        nse_good_enough=0.5,
    )
    assert result["recommended_action"] == "A10_FREEZE"


def test_peak_bias_strategy_targets_runoff_routing_composite():
    strategy = CalibrationStrategyRegistry().get("xaj-peak-bias-v1")
    assert strategy.objective == "composite"
    assert strategy.param_groups == ("runoff", "routing")
