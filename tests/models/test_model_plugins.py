from hydro_agent.models.registry import default_model_registry
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry
from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.orchestration import SkillOrchestrator


def test_strategy_registry_is_model_scoped():
    registry = CalibrationStrategyRegistry()
    assert "gr4j-bounded-v1" in registry.list_ids(model_id="gr4j")
    assert "xaj-bounded-v1" not in registry.list_ids(model_id="gr4j")
    strategy = registry.get("gr4j-bounded-v1", model_id="gr4j")
    assert strategy.param_groups == ("production", "exchange", "routing")


def test_diagnosis_skill_resolved_from_plugin_not_hardcoded_branch():
    skills = SkillRegistry()
    skills.reload()
    assert "gr4j-calibration-diagnosis" in skills._diagnosis_skill_ids("gr4j")
    assert "hbv-calibration-diagnosis" in skills._diagnosis_skill_ids("hbv")
    assert "tank-calibration-diagnosis" in skills._diagnosis_skill_ids("tank")
    assert "sac-sma-calibration-diagnosis" in skills._diagnosis_skill_ids("sac-sma")
    assert "xaj-calibration-diagnosis" in skills._diagnosis_skill_ids("xaj")
    assert "xaj-calibration-diagnosis" not in skills._diagnosis_skill_ids("gr4j")


def test_orchestrator_invokes_gr4j_diagnosis_skill():
    skills = SkillRegistry()
    skills.reload()
    orch = SkillOrchestrator(skills=skills)
    diagnosis = {
        "hypothesis": "MODEL",
        "phenomenon": "洪峰偏晚",
        "recommended_param_groups": ["routing"],
        "recommended_strategy_id": "gr4j-routing-refine-v1",
        "model_id": "gr4j",
        "metrics": {"nse": 0.4},
    }
    skill_id = default_model_registry().diagnosis_skill_id("gr4j")
    assert skill_id == "gr4j-calibration-diagnosis"
    inv = orch.invoke_skill(skill_id, diagnosis=diagnosis, view=None)
    assert inv.skill_id == skill_id
    assert inv.output_contract == "DiagnosisHypothesis"
    assert inv.output["parameter_groups"]


def test_xaj_still_default_plugin():
    registry = default_model_registry()
    assert registry.get("xaj").descriptor.default_strategy_id == "xaj-bounded-v1"
    assert set(registry.list_ids()) >= {"xaj", "gr4j", "hbv", "tank", "sac-sma"}
