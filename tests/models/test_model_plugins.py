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


def test_orchestrator_compiles_live_skill_choice_without_cross_model_leakage():
    skills = SkillRegistry()
    skills.reload()
    orch = SkillOrchestrator(skills=skills)
    diagnosis = {
        "hypothesis": "MODEL",
        "phenomenon": "洪峰系统性偏晚且水量接近",
        "model_id": "gr4j",
        "metrics": {"nse": 0.4, "pbias_percent": 1.0, "peak_timing_lag_days": 2.0},
    }

    plan, _ = orch.plan_calibration(
        diagnosis,
        proposed_strategy_id="gr4j-routing-refine-v1",
        proposed_param_groups=("routing",),
        proposed_objective="composite",
    )

    assert plan.strategy_id == "gr4j-routing-refine-v1"
    assert plan.parameter_groups == ("routing",)
    assert plan.objective == "composite"

    fallback, _ = orch.plan_calibration(
        diagnosis,
        proposed_strategy_id="xaj-routing-refine-v1",
        proposed_param_groups=("evap",),
        proposed_objective="composite",
    )
    assert fallback.strategy_id == "gr4j-bounded-v1"
    assert "evap" not in fallback.parameter_groups


def test_xaj_still_default_plugin():
    registry = default_model_registry()
    assert registry.get("xaj").descriptor.default_strategy_id == "xaj-bounded-v1"
    assert set(registry.list_ids()) >= {"xaj", "gr4j", "hbv", "tank", "sac-sma"}


def test_only_source_verified_kernel_advertises_product_calibration():
    registry = default_model_registry()
    assert registry.get("xaj").descriptor.validation_status == "source_verified"
    assert registry.get("xaj").descriptor.supports_calibration is True
    assert registry.get("gr4j").descriptor.validation_status == "source_verified"
    assert registry.get("gr4j").descriptor.supports_calibration is True
    assert registry.get("hbv").descriptor.validation_status == "source_verified"
    assert registry.get("hbv").descriptor.supports_calibration is True
    assert registry.get("tank").descriptor.validation_status == "source_verified"
    assert registry.get("tank").descriptor.supports_calibration is True
    for model_id in ("sac-sma",):
        descriptor = registry.get(model_id).descriptor
        assert descriptor.validation_status != "source_verified"
        assert descriptor.supports_calibration is False


def test_runtime_adapters_advertise_only_commands_they_implement():
    registry = default_model_registry()
    for model_id in registry.list_ids():
        assert registry.get(model_id).runtime_adapter.capabilities == frozenset(
            {"forecast", "calibrate"}
        )
