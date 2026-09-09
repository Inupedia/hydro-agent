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


def test_skills_registry_has_diagnose_and_adapt_cards():
    skills = SkillRegistry()
    ids = {s.skill_id for s in skills.list()}
    assert {"data-check", "forecast-diagnose", "bounded-adapt"} <= ids
    diagnose = skills.get("forecast-diagnose")
    assert "A06_DIAGNOSE" in diagnose.recommended_actions


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
    )
    assert result["hypothesis"] == "MODEL"
    assert result["recommended_strategy_id"] == "xaj-peak-bias-v1"
    assert result["recommended_param_groups"] == ["runoff", "routing"]
    assert result["recommended_objective"] == "composite"
    assert len(result["hypotheses"]) >= 2
    ids = {item["id"] for item in result["hypotheses"]}
    assert "MODEL" in ids and "FORCING" in ids


def test_peak_bias_strategy_targets_runoff_routing_composite():
    strategy = CalibrationStrategyRegistry().get("xaj-peak-bias-v1")
    assert strategy.objective == "composite"
    assert strategy.param_groups == ("runoff", "routing")
