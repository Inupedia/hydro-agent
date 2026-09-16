from hydro_agent.optimization.strategies import CalibrationStrategyRegistry
from hydro_agent.skills import SkillRegistry
from hydro_agent.standards import StandardRepository


def test_strategy_registry_exposes_distinct_experiment_strategies():
    registry = CalibrationStrategyRegistry()
    assert set(registry.list_ids()) >= {
        "xaj-bounded-v1",
        "xaj-peak-bias-v1",
        "xaj-local-refine-v1",
        "xaj-hydrologist-manual-v1",
    }
    assert (
        registry.get("xaj-bounded-v1").random_seed != registry.get("xaj-peak-bias-v1").random_seed
    )
    assert registry.get("xaj-local-refine-v1").local_scale == 0.25


def test_skills_registry_exposes_focused_hydrology_cards():
    skills = SkillRegistry()
    ids = {s.skill_id for s in skills.list()}
    assert {
        "hydrology-data-review",
        "hydrologic-evidence-review",
        "xaj-calibration-diagnosis",
        "calibration-experiment-design",
        "calibration-result-review",
        "hydrology-reporting",
    } == ids
    assert "data-check" not in ids
    assert "forecast-diagnose" not in ids
    diagnose = skills.get("hydrologic-evidence-review")
    assert "A04_DIAGNOSE" in diagnose.recommended_actions
    cal = skills.get("xaj-calibration-diagnosis")
    assert "A05_OPTIMIZE" in cal.recommended_actions
    standards = StandardRepository()
    assert standards.grade_dc_bing() == 0.5
    assert skills.min_scheme_grade() == "丙"
    cfg = skills.gbt_accuracy_config()
    assert cfg.min_scheme_grade == "丙"
    assert cfg.grade_dc_bing == 0.5


def test_peak_bias_strategy_targets_runoff_routing_composite():
    strategy = CalibrationStrategyRegistry().get("xaj-peak-bias-v1")
    assert strategy.objective == "composite"
    assert strategy.param_groups == ("runoff", "routing")
